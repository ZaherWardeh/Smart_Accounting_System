# Smart Accounting System

A small FastAPI accounting web app — accounts, transactions, and reports —
plus an AI assistant ("ريما" / "Rima") that answers accounting questions
against the app's own data, powered by
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

Open `http://127.0.0.1:8000/` — a small built-in website (no separate
frontend project, no build step) covering the whole app:

| Page | Route | What it does |
| --- | --- | --- |
| Dashboard | `/` | Financial summary + links into the other pages. |
| Accounts | `/accounts` | The chart of accounts as a collapsible tree, sorted by code; add, edit, delete an account. |
| Transactions | `/transactions` | Browse journal entries; add/edit with dynamic debit/credit lines and live balance validation; delete. |
| Reports | `/reports` | Financial summary, statement of account (with an optional date range), and account balance (single or multiple accounts). |
| Chat with Rima | `/chat` | Ask Rima anything accounting-related; keeps `conversation_id` in `localStorage` so memory persists across reloads until you hit "محادثة جديدة" (new conversation). |

All five pages are plain HTML/CSS/JS (`static/*.html` + a shared
`static/app.css`), talking to the JSON API below via `fetch`. Deleting an
account is blocked (409) if it has child accounts or any transactions
posted to it, so the chart of accounts can't be silently orphaned.

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

Install that into whichever Python runs `tray.pyw` (double-clicking uses
whatever your system associates `.pyw` files with — it doesn't have to be
this project's `.venv`). The server subprocess itself always uses this
project's `.venv` interpreter regardless, auto-detected from `tray.pyw`'s
own location, so it has the real app dependencies even if the interpreter
running the tray icon doesn't.

Double-click `tray.pyw` (no console window opens), or run it explicitly:

```bash
.venv\Scripts\pythonw.exe tray.pyw
```

Server output goes to `server.log` in the project root — check it first if
the tray icon turns red on startup.

Want to put this on a real server? See `DEPLOYMENT.md` — Ubuntu + Docker,
behind Nginx.

## Architecture

### JSON API

The pages above are all thin `fetch` clients over this API — use it
directly too if you want (Swagger UI at `/docs`).

| Method & path | Purpose |
| --- | --- |
| `GET /accounts/`, `GET /accounts/{id}` | List / fetch accounts. |
| `POST /accounts/`, `PUT /accounts/` | Create / update an account (`id` in the body for update). |
| `DELETE /accounts/{id}` | Delete an account — `409` if it has child accounts or transactions posted to it. |
| `GET /transactions/`, `GET /transactions/{id}` | List / fetch journal entries with their line items. |
| `POST /transactions/`, `PUT /transactions/` | Create / update a transaction — `406` if debits ≠ credits. |
| `DELETE /transactions/{id}` | Delete a transaction (its line items cascade with it). |
| `GET /reports/summery` | Total income / expense / balance. |
| `GET /reports/chart-of-accounts` | Every account with a derived `account_type` (`master`/`book`) and labeled `closeIn`. |
| `GET /reports/statement/{acc_id}?date_from=&date_to=` | Statement of account — a master account rolls up its descendants. |
| `GET /reports/balance?acc_ids=1&acc_ids=2&as_of_date=&date_from=&date_to=` | Balance for one or more accounts, combined + per-account breakdown. |
| `POST /reports/ask_ai` | Ask Rima — see below. Can also carry an `attachment` (a document image); reply includes `pending_drafts`. |
| `GET /drafts/{conversation_id}` | Unsaved operations (entry/new-account drafts) Rima is still collecting for that conversation. |
| `POST /drafts/{conversation_id}/{kind}/confirm`, `.../cancel` | A real button press: save the draft exactly as it stands, or discard it. `kind` is `transaction` or `account`. |
| `GET /transactions/{id}/document` | The source document image saved with an entry, if any (see `has_document` on the transaction). |
| `GET /health` | `{"status": "ok", "llm_connected": bool}` — used by the tray launcher. |

### Request flow (Rima)

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

### Recording a transaction or a new account through Rima

Rima can also *write* — record a journal entry, or create a new account for one
— but she never writes directly. She can only propose fields to a **draft**
that the **server** validates, orders and gates; the model just phrases the
conversation. This is deliberate: an LLM told "ask for whatever's missing" will
occasionally invent an account or skip a question, so the required-field order,
every validation rule and the save-only-after-confirmation gate all live in
`drafts.py`, not in the prompt.

- **Transaction** (one debit line, one credit line, one amount): required
  fields are asked **in a fixed order** — debit account, then credit account,
  then amount — each with server-ranked suggestions (`update_transaction_draft`
  returns `next_step` and `suggestions`; the model must ask only about
  `next_step`). Date defaults to today (or the attached document's date).
- **New account**: required fields, also in order — name, parent account
  (never a top-level account), and where it closes (Balance Sheet / P&L /
  Trading). The **code defaults to the parent's code + the next two digits**
  (`next_child_code` in `drafts.py`, following the scheme described below);
  the user can accept it or give another valid one. The account is always
  created as a detail (book) account.
- **Confirmation gate**: once a draft is complete its status becomes
  `awaiting_confirmation`. `commit_transaction`/`commit_account` refuse in the
  *same* request that completed the draft — the model must read the draft
  back and get an actual later message (or a UI button press) before it can
  save. Any further `update_*` call re-opens confirmation.
- **Unsaved operations are never silently dropped.** A draft lives in the
  `RimaDrafts` table (not memory), so it survives a server restart. Every
  `/reports/ask_ai` reply lists open drafts in `pending_drafts`, and the system
  prompt is handed a block each turn instructing Rima to remind the user (after
  answering whatever they actually asked) that they can **confirm, modify, or
  abort**. The mobile app and website also poll `GET /drafts/{id}` when the
  chat opens and show the same three actions as buttons, so a user never has
  to get the model to cooperate just to get rid of a stuck draft.
- **Source documents**: an image (a bill, a receipt) can be sent with the
  question. It's read once by a separate, tool-less Gemini vision call
  (`documents.extract_document_facts`) with a fixed JSON schema — so text
  printed on the document can't act as instructions, only as data. Suggested
  accounts are ranked **document first, then the user's words, then history**;
  a document's total/date are only ever *proposed*, never silently filled in.
  The image is kept in `RimaAttachments` until an entry is confirmed, then
  moved onto that transaction's own `document`/`document_mime`/`document_name`
  columns (and discarded on cancel). `GET /transactions/{id}/document` serves
  it back; list endpoints only send `has_document`, never the bytes
  (`document` is a deferred column).
- If the model's own call fails *after* a write already went through (e.g. a
  quota error while composing the reply), the user still gets told what was
  saved — `agent_loop` catches that case and answers from the tool's own
  result, not from the model.

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
| `tools.py` | The three read-only domain tools (`get_chart_of_accounts`, `get_account_transactions`, `get_account_balance`), plain functions against the DB — no LLM. |
| `drafts.py` | The governed write path: transaction/account drafts, validation, the account-code generator, the suggestion ranker, and the 6 write tools Rima calls (`update_transaction_draft`, `commit_transaction`, `cancel_transaction_draft`, `update_account_draft`, `commit_account`, `cancel_account_draft`). |
| `documents.py` | Source-document images: decoding/validating an upload, the tool-less vision extraction call, and storage helpers (`RimaAttachments`, stale-upload cleanup). |
| `graph.py` | The Gemini client setup, `AgentState`, the single `agent_loop` node and its tool-calling loop, the conversation-history store. `run_agent(db, conversation_id, question, attachment=None)` is the entry point `main.py` calls. |
| `reports.py` | `get_financial_summary`, used by `/reports/summery` — the only other place in the app that touches transaction data outside the AI path. |
| `models.py` / `schemas.py` / `database.py` | SQLAlchemy models, Pydantic schemas, SQLite session setup — unchanged in shape by this migration except the Pydantic v2 fixes below. |
| `static/*.html` / `static/app.css` | The built-in website — dashboard, accounts, transactions, reports, and the Rima chat UI — see the table above. |
| `mobile/` | Flutter app (Android/iOS) mirroring the website, plus voice: speak to Rima and she answers out loud. See [mobile/README.md](mobile/README.md). |
| `Dockerfile` / `docker-compose.yml` / `.dockerignore` / `deploy/nginx.conf` / `DEPLOYMENT.md` | Deploying this on your own Ubuntu server with Docker, behind Nginx — see `DEPLOYMENT.md`. |
| `tray.pyw` / `requirements-tray.txt` | Windows system tray launcher — starts the server, opens `/chat`, shows connection status. See "Windows tray launcher" above. |

### The three domain tools

Tools are shaped around how an accountant actually reasons — chart, then
ledger, then balance — rather than generic pandas filter/groupby calls:

1. **`get_chart_of_accounts()`** — every account with `id`, `code`, `name`,
   `closeIn` (labeled Balance Sheet / P&L / Trading), `parentAccount`, and a
   derived `account_type` (`"master"` if any other account lists it as a
   parent, otherwise `"book"`) — **sorted by `code` ascending** (an account
   without a code sorts last). `code` is the account's short identifier in
   the chart of accounts (e.g. `"001"`); the tool's own description tells
   the model to quote it alongside the name when it's set. The model calls
   this first to resolve a name like "sales" or "الصندوق" to an id.
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
   single collapsed number — so the answer is auditable. The breakdown is
   sorted by `code` and each entry includes it. The tool does not sign the
   net figure into "the balance is X" (the schema has no
   asset/liability/equity/revenue/expense classification); that
   interpretation is left to Rima's own accounting judgment during answer
   synthesis.

### Account codes

Every account has an optional `code`, shown next to its name throughout the
site and sorted on wherever accounts are listed (the Accounts tree, the
chart of accounts, statement/balance selectors, and the balance
breakdown).

Codes are **hierarchical and parent-prefixed**, not flat: each root account
gets a 3-digit code (`001`, `002`, ...), and every account below that gets
its parent's code plus a 2-digit position among that parent's own children
— so Assets = `001`, Assets' 1st child (Fixed Assets) = `00101`,
Liabilities = `002`, and so on down as many levels as the tree goes (e.g.
`0010201` is the 1st child of `00102`, which is Assets' 2nd child). A plain
lexicographic string sort on these reconstructs the exact depth-first tree
order with no separate tree-walk needed — that only works because every
level adds a *fixed* 2 digits; a numeric-aware sort would compare the
whole digit run as one number and break the nesting (see the comments in
`scripts/backfill_account_codes.py` for why).

`scripts/backfill_account_codes.py` is the one-off migration that added
the column and assigned these codes to this repo's dev `accounting.db` —
kept for reference if you're migrating your own pre-existing database; a
fresh/empty database gets the `code` column for free from
`Base.metadata.create_all()`.

When Rima creates a new account, `drafts.next_child_code` computes the
default the same way: the highest existing code among that parent's direct
children, plus one, zero-padded to two digits (or `parent_code + "01"` if it
has no children yet). If the 99 slots under a parent are full it reuses the
lowest free one, and if none are free (or the parent itself has no code) no
default is offered — the user has to pick a different parent or type a
code by hand.

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
- `tests/test_main_endpoints.py` — the website/API endpoints via FastAPI's
  `TestClient` against an isolated seeded DB (never the real
  `accounting.db`): every page route serves HTML, the three new report
  endpoints, and the account/transaction delete safety checks (blocked by
  child accounts, blocked by existing transactions, cascading delete of a
  transaction's line items). Uses `poolclass=StaticPool` in
  `tests/conftest.py`'s `db_session` fixture — `TestClient` runs sync route
  handlers in a worker thread, and plain in-memory SQLite otherwise hands
  each thread a separate, empty database.
- `tests/test_rima_drafts.py` — `drafts.py` directly, against a chart shaped
  like the real hierarchical one: required-field order for both the
  transaction and account flows, every validation rule, the account-code
  generator (including the 99-slot overflow and no-code-parent cases),
  the confirmation gate (same-request commit refused, a later one allowed,
  an edit re-opening it), a new account auto-filling the debit/credit slot
  of a transaction mid-flow, and the document-attachment behaviour
  (suggestion priority, the proposed-not-filled amount, byte-for-byte
  storage on commit, discard on cancel).
- `tests/test_rima_e2e.py` — the same flows through the full `agent_loop`
  with a scripted Gemini client: proves the *server*, not the model, is what
  enforces the rules (an early `commit_transaction` call is refused, smuggled
  arguments like a different `conversation_id` are rejected, a hostile
  instruction embedded in a document's text has no tools to act on), plus the
  pending-drafts reminder block appearing in the system prompt and the
  fallback that reports a successful save even if the model's own next call
  then fails (e.g. a quota error).
- `tests/test_rima_api.py` — the HTTP layer: attachment decoding/validation
  (real image bytes required, size cap, declared MIME type never trusted),
  the `/drafts` routes (list/confirm/cancel, refusing an incomplete or
  missing draft), the document endpoints (round-trips the saved image,
  `has_document` without shipping the bytes), and the legacy-database
  migration (`database.ensure_columns`) against a temp SQLite file built with
  the pre-Rima schema.
