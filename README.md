# Smart Accounting System

A small FastAPI accounting service with an AI assistant ("ريما" / "Rima") that
answers accounting questions against the app's own data, powered by
[LangGraph](https://langchain-ai.github.io/langgraph/) and Gemini
(`gemini-2.5-flash` via `google-genai`).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```
API_KEY=your-gemini-api-key
```

A free-tier Gemini API key is sufficient for development.

Run the API:

```bash
uvicorn main:app --reload
```

Run the tests:

```bash
pytest
```

## Architecture

### Request flow

```
POST /reports/ask_ai  { "question": "..." }
        |
        v
   classify_intent  (Gemini call, JSON: intent/confidence/reason)
        |
        v
      route (no LLM call — pure routing on the classification result)
        |
        +-- low confidence          --> handle_ambiguous     --> END
        +-- Out of Scope            --> handle_out_of_scope  --> END
        +-- Greeting                --> handle_greeting      --> END
        +-- Accounting Inquiry /
            Financial Analysis /
            Data Request            --> agent_loop           --> END
```

`agent_loop` is where the real work happens for data questions. It binds
three domain tools to the Gemini call and runs a bounded (max 6 rounds)
call -> execute-tool -> feed-result-back loop until the model responds with
plain text instead of a tool call. That text is the final answer.

Everything stays on Gemini end to end — no LLM-generated code is ever
`exec()`'d (the old pipeline's two `exec()` calls are gone). Every prompt is
in Arabic with a hard "always answer in the user's language" rule, and the
"Rima" persona carries through every branch, including `agent_loop`.

### Files

| File | Role |
| --- | --- |
| `tools.py` | The three domain tools (`get_chart_of_accounts`, `get_account_transactions`, `get_account_balance`), plain functions against the DB — no LLM. |
| `graph.py` | `AgentState`, the graph nodes, routing, and `agent_loop`'s tool-calling loop. `run_agent(db, question)` is the entry point `main.py` calls. |
| `analysis.py` | `get_financial_summary` (used by `/reports/summery`) plus the single-shot prompt functions (`intent_analysis`, `welcoming_proc`, `prompt_Ambiguity_Response`, `prompt_Out_of_Scope_Response`) and the shared Gemini client / `exec_prompt` helper that the simple graph nodes call. |
| `models.py` / `schemas.py` / `database.py` | SQLAlchemy models, Pydantic schemas, SQLite session setup — unchanged in shape by this migration except the Pydantic v2 fixes below. |

### The three domain tools

Tools are shaped around how an accountant actually reasons — chart, then
ledger, then balance — rather than generic pandas filter/groupby calls:

1. **`get_chart_of_accounts()`** — every account with `id`, `name`, `closeIn`
   (labeled Balance Sheet / P&L / Trading), `parentAccount`, and a derived
   `account_type` (`"master"` if any other account lists it as a parent,
   otherwise `"book"`). The model calls this first to resolve a name like
   "sales" or "الصندوق" to an id.
2. **`get_account_transactions(acc_id, date_from=None, date_to=None)`** —
   transaction lines for that account (all-time if no range given). A master
   account pulls transactions from every descendant book account too.
3. **`get_account_balance(acc_ids, as_of_date=None, date_from=None, date_to=None)`**
   — takes a *list* of account ids so the model can aggregate related
   accounts in one call (e.g. every cash/bank account for a "liquidity"
   question). Branches per account on its own `closeIn`: Balance Sheet
   accounts are cumulative as of `as_of_date` (defaults to today); P&L /
   Trading accounts require a `date_from`/`date_to` period. Master accounts
   sum every descendant book account recursively. Returns a combined
   `debit_sum`/`credit_sum`/`net` plus a per-account `breakdown` — never a
   single collapsed number — so the answer is auditable. The tool does not
   sign the net figure into "the balance is X" (the schema has no
   asset/liability/equity/revenue/expense classification); that
   interpretation is left to Rima's own accounting judgment during answer
   synthesis.

## Known limitations (carried over, not introduced by this migration)

- **Name collisions**: if a name matches more than one account, `agent_loop`
  is instructed to list every candidate (name, parent/path, closing type)
  and ask the user to ask again more specifically — the same
  "please be more specific" pattern the ambiguous-intent handler already
  uses. This works because `/reports/ask_ai` is a single stateless
  question-and-answer call, not a running conversation. True back-and-forth
  ("the first one") would need conversation history threaded through the
  API, which is out of scope here.
- **Cross-cutting concepts** like "liquidity" have no dedicated
  chart-of-accounts flag — the model infers which accounts qualify from
  their names/hierarchy, the same way the original pipeline did. A future
  schema addition (an account `category` field, or a numbered
  chart-of-accounts range convention) would make this deterministic instead
  of inferred, if that matters for a client-facing deployment.
- **Ratio-style financial analysis** (liquidity ratios, profitability
  trends) isn't implemented by the three tools directly — they answer
  lookup/reporting questions well ("what's in the chart of accounts",
  "cash movements in March", "AR balance today"), and analysis on top of
  that still leans on the model's own domain knowledge, same as before.
- Auth, rate limiting, and moving off SQLite are all still open — out of
  scope for this migration.

## Tests

- `tests/test_tools.py` — the three tool functions against a seeded
  in-memory SQLite DB: master/book rollup, closing-type branching (Balance
  Sheet vs P&L), and date-range edges.
- `tests/test_graph_nodes.py` — `classify_intent`/`route`/the simple
  single-shot nodes, with the Gemini client mocked.
- `tests/test_agent_loop_e2e.py` — `agent_loop`'s tool-calling loop with a
  stub client that scripts a multi-tool-call exchange, including the
  max-rounds guard and an unknown-tool-name response.
- `tests/test_graph_e2e.py` — the full compiled graph via `run_agent`,
  covering the data-question path (through `agent_loop`), the greeting
  path, and the low-confidence/ambiguous path.
