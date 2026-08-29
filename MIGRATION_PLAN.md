# Smart_Accounting_System → LangGraph + Anthropic Migration Plan

Scanned from the connected repo (`analysis.py`, `main.py`, `models.py`, `schemas.py`, `database.py`, `requirements.txt`) on 2026-08-26.

## What's there today

`analysis.py` hand-rolls a 5-call sequential pipeline against the Gemini API (`google-genai`, `gemini-2.5-flash`):

1. `intent_analysis()` — classifies into Greeting / Accounting Inquiry / Financial Analysis / Data Request / Out of Scope, returns JSON.
2. `analyze_with_ai()` acts as the router: low confidence → `prompt_Ambiguity_Response()`; Out of Scope → `prompt_Out_of_Scope_Response()`; Greeting → `welcoming_proc()`; the three data intents → `inquiry_proc()`.
3. Inside `inquiry_proc()`: an LLM call generates raw pandas filter code as text, which is passed straight to **`exec(code_from_ai)`**.
4. A second LLM call decides whether summarization is needed and, if so, generates more pandas code, again run through **`exec(code_details)`**.
5. A final LLM call receives the filtered/summarized `df` as JSON and answers in the user's language, in character as "Rima" (رِيما), an Arabic-speaking accountant persona.

Entry point: `GET /reports/ask_ai/{question}` in `main.py` — question arrives as a raw URL path segment.

Everything in the prompts is already in Arabic with a hard "always answer in the user's language" rule — that persona and behavior carry over unchanged, only the transport (Gemini → Anthropic) and control flow (linear Python calls → LangGraph graph) change.

## Target architecture

A `StateGraph` with one shared state object flowing through typed nodes, replacing the linear function calls in `analyze_with_ai()`.

**State** (`AgentState`, a `TypedDict`):
`question`, `intent`, `confidence`, `reason`, `df` (the loaded transactions frame, not part of persisted state but held per-run), `filter_result`, `needs_summary`, `summary_result`, `answer`, `error`.

**Nodes:**

| Node | Replaces | Model call? |
|---|---|---|
| `classify_intent` | `intent_analysis()` | yes — plain text/JSON response |
| `route` (conditional edge, not an LLM node) | the if/elif chain in `analyze_with_ai()` | no |
| `handle_ambiguous` | `prompt_Ambiguity_Response()` | yes |
| `handle_out_of_scope` | `prompt_Out_of_Scope_Response()` | yes |
| `handle_greeting` | `welcoming_proc()` | yes |
| `filter_data` | the first `exec(code_from_ai)` block | yes, **as a tool call**, not free text |
| `maybe_summarize` | the second `exec(code_details)` block | yes, **as a tool call** |
| `synthesize_answer` | the final prompt in `inquiry_proc()` | yes |

Edges: `classify_intent → route →` one of `{handle_ambiguous, handle_out_of_scope, handle_greeting, filter_data}`; `filter_data → maybe_summarize → synthesize_answer → END`; the three handler nodes go straight to `END`.

## Killing the `exec()` problem as part of the migration, not after it

Since `filter_data` and `maybe_summarize` are being rebuilt as LangGraph nodes anyway, they get rebuilt as **Anthropic tool calls against a fixed function**, not free-form code generation:

```python
FILTER_TOOL = {
    "name": "filter_transactions",
    "description": "Filter the transactions DataFrame by one or more conditions",
    "input_schema": {
        "type": "object",
        "properties": {
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "column": {"type": "string", "enum": ["credit", "debit", "acc_id", "acc_name",
                                                                 "acc_closeIn", "acc_parent_account", "transaction_date"]},
                        "op": {"type": "string", "enum": ["==", "!=", ">", ">=", "<", "<=", "contains", "between"]},
                        "value": {}
                    },
                    "required": ["column", "op", "value"]
                }
            }
        },
        "required": ["conditions"]
    }
}
```

Claude returns structured `conditions`; a small Python function (`apply_filter(df, conditions)`) applies them with pandas boolean masking — no string of Python ever reaches `exec()`. Same pattern for summarization (`GROUPBY_TOOL`: `group_by` column(s) + `agg` operation, applied via `df.groupby(...).agg(...)`). This closes tech-debt item #1 from the original review as a byproduct of the rebuild, not a separate pass.

## Model / SDK swap

- `google-genai` → `anthropic` SDK. `client.models.generate_content(model="gemini-2.5-flash", ...)` → `client.messages.create(model=..., messages=..., tools=[...])`.
- `.env`: `API_KEY` → `ANTHROPIC_API_KEY` (keep both during transition so the old code path still runs until cut over).
- Suggest `claude-sonnet-4-5` for classify/synthesize (quality on Arabic reasoning + persona consistency matters most here) — cheaper `claude-haiku-4-5` is a reasonable option for `filter_data`'s tool call if cost becomes a concern later, but start with one model everywhere and split only if you see a reason to.
- The "Rima" persona block and the "always answer in the user's language" rule move verbatim into the new node prompts — no behavior change, just carrier.

## Touching `main.py` and `schemas.py` while we're in there

Two items from the original tech-debt list sit directly in the files this migration already opens, so folding them in now avoids a second pass:

- `GET /reports/ask_ai/{question}` → `POST /reports/ask_ai` with `question` in the request body. Trivial fix, and it's the exact endpoint being rewired to call the graph instead of `analyze_with_ai()`.
- `schemas.py`: `class Config: orm_mode = True` → `model_config = ConfigDict(from_attributes=True)`; `AccountOut.from_orm(x)` in `main.py` → `AccountOut.model_validate(x)`. Pydantic 2.12 is already pinned in `requirements.txt`, so this is a correctness fix, not optional.

Everything else on the tech-debt list (auth, rate limiting, SQLite → real DB) stays out of scope for this migration — worth flagging so it doesn't get silently entangled with the LangGraph work.

## Staged build order

1. **Deps & env** — add `langgraph`, `anthropic` to `requirements.txt`; add `ANTHROPIC_API_KEY`.
2. **Tools first** — write `apply_filter()` / `apply_groupby()` as plain, independently testable Python functions (no LLM, no LangGraph yet). This is the part that actually removes the security hole, so it's worth landing and testing on its own before the graph exists.
3. **Graph skeleton** — `AgentState`, the 7 nodes as thin wrappers, conditional routing edge, compiled graph — using the Anthropic client for every node.
4. **Wire into FastAPI** — new `POST /reports/ask_ai` calls `graph.invoke()`; old `analyze_with_ai()` path removed once parity is confirmed.
5. **Pydantic v2 fix** in `schemas.py` + the two `from_orm` call sites in `main.py`.
6. **Tests** — unit tests for `apply_filter`/`apply_groupby` (no mocking needed, pure functions), a mocked-Anthropic-client test per node, one end-to-end graph test with a stub client.
7. **README** — architecture section describing the graph, setup instructions, env vars.

Steps 2 and 3 are the ones worth doing carefully; 4–7 are mechanical once the graph exists.
