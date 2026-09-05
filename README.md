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

Open `http://127.0.0.1:8000/chat` for a small built-in chat UI to talk to
Rima directly (no separate frontend project needed) — good for manual
testing. It's a single static page (`static/chat.html`) served by FastAPI;
it keeps its own `conversation_id` in the browser's `localStorage`, so
memory persists across page reloads until you hit "محادثة جديدة" (new
conversation).

Run the tests:

```bash
pytest
```

### Windows tray launcher

`tray.pyw` is a one-click alternative to the `uvicorn` command above: it
starts the server as a background process, shows a system tray icon (yellow
while starting, green once the server *and* the Gemini client are up, red if
either isn't), and opens `/chat` in your browser automatically. "Quit" in the
tray menu stops the server.

```bash
pip install -r requirements-tray.txt   # pystray + Pillow, only needed for this launcher
```

Then double-click `tray.pyw` (associated with `pythonw.exe`, so no console
window opens), or run it explicitly with the venv's interpreter:

```bash
.venv\Scripts\pythonw.exe tray.pyw
```

Server output goes to `server.log` in the project root.

Want to put this on AWS for testing? See `DEPLOYMENT.md`.

## Architecture

### Request flow

```
POST /reports/ask_ai  { "conversation_id": "...", "question": "..." }
        |
        v
   agent_loop  (single LangGraph node) --> END
```

There is no separate intent-classification call or hard-coded routing
anymore. One system prompt (`SYSTEM_PROMPT_CORE` in `graph.py`) carries the
"Rima" persona, the language rule, the "accounting questions only, decline
anything else politely" scope rule, and the ambiguity-handling rule
("don't guess, ask for clarification") all at once, and `agent_loop` binds
the three domain tools and runs a bounded (max 6 rounds) call ->
execute-tool -> feed-result-back loop until the model responds with plain
text instead of a tool call. That text is the final answer, whether the
turn ends up being a greeting, a scope refusal, a clarifying question, or an
actual data answer — the model decides inline instead of a prior
classification step forcing the branch.

No LLM-generated code is ever `exec()`'d (the old pipeline's two `exec()`
calls are gone, and stay gone).

### Conversation memory

`/reports/ask_ai` now takes a `conversation_id` (generated and kept by the
caller — e.g. one GUID per chat session in the client app) alongside
`question`. `graph.py` keeps an in-memory, process-local store
(`conversation_id -> list[Content]`) and threads the full turn history into
every `generate_content` call for that conversation, so the model has real
multi-turn memory (it can resolve "the first one" against a list of
candidates it gave two turns ago, for example).

Two things worth knowing about this:

- **It's in-memory, not persisted.** History is lost if the server process
  restarts (including `uvicorn --reload` picking up a code change). If that
  becomes a problem, the store would need to move to a DB table or an
  external cache — same `conversation_id -> contents` shape, different
  backing store.
- **The system prompt is authored once, not resent as growing history.** It
  goes in via Gemini's `system_instruction` config field (sent with every
  call, since `generate_content` itself is stateless per request) rather
  than being baked into the `contents` list, so it never gets duplicated
  into the conversation history as turns accumulate. The one exception is a
  short "introduce yourself" instruction appended only when
  `conversation_id` has no history yet (i.e. this is the first turn) — Rima
  only introduces herself once per conversation, not on every reply.

### Files

| File | Role |
| --- | --- |
| `tools.py` | The three domain tools (`get_chart_of_accounts`, `get_account_transactions`, `get_account_balance`), plain functions against the DB — no LLM. |
| `graph.py` | The Gemini client setup, `AgentState`, the single `agent_loop` node and its tool-calling loop, the conversation-history store. `run_agent(db, conversation_id, question)` is the entry point `main.py` calls. |
| `reports.py` | `get_financial_summary`, used by `/reports/summery` — the only other place in the app that touches transaction data outside the AI path. |
| `models.py` / `schemas.py` / `database.py` | SQLAlchemy models, Pydantic schemas, SQLite session setup — unchanged in shape by this migration except the Pydantic v2 fixes below. |
| `static/chat.html` | The built-in Rima testing chat UI, served at `GET /chat`. |
| `Dockerfile` / `.dockerignore` / `DEPLOYMENT.md` | Containerizing and putting this on AWS for testing — see `DEPLOYMENT.md`. |
| `tray.pyw` / `requirements-tray.txt` | Windows system tray launcher — starts the server, opens `/chat`, shows connection status. See "Windows tray launcher" above. |

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

## Known limitations

- **Name collisions**: if a name matches more than one account, `agent_loop`
  is instructed to list every candidate (name, parent/path, closing type)
  and ask the user to specify. With conversation memory in place, genuine
  back-and-forth now works ("the first one" resolves against the candidate
  list Rima gave earlier in the same `conversation_id`) — this is no longer
  the single stateless call it used to be. There's still no *deterministic*
  check that forces a pause on a true collision, though: it's the model
  following the prompt's instruction, not a hard-coded gate the way
  `route`'s old low-confidence branch was. Worth hardening if this ever
  misfires in practice — a code-level check after `get_chart_of_accounts`
  resolution would remove the reliance on prompt compliance entirely.
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
- `tests/test_memory.py` — the conversation-history store in isolation
  (round-trips, per-`conversation_id` isolation), and that the
  "introduce yourself" instruction is only present on the first turn of a
  conversation.
- `tests/test_agent_loop_e2e.py` — `agent_loop`'s tool-calling loop with a
  stub client that scripts a multi-tool-call exchange, including the
  max-rounds guard and an unknown-tool-name response.
- `tests/test_graph_e2e.py` — the full compiled graph via `run_agent`:
  a plain reply with no tool calls, memory carried across two calls in the
  same conversation, and two different `conversation_id`s staying isolated
  from each other.
