"""Governed write-tools for Rima: record a transaction, create an account.

The LLM never writes to the books directly. It can only *propose* fields to a
server-side draft; the server validates every field, decides what is still
missing and in which order to ask for it, and only saves once the draft is
complete AND the user has confirmed in a later message (or pressed a button).
Drafts live in the DB (RimaDraft) so an unanswered one survives restarts and is
never silently dropped or auto-saved.

Tools take (db, ctx, **args): `ctx` (conversation id, request id, the user's
raw message, today's date) is injected by graph._run_tool and is not part of
the schema the model sees, so the model can't address another conversation.
"""

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date as date_cls, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from models import Accounts, RimaAttachment, RimaDraft, TransactionsDetail, TransactionsMaster
from tools import CLOSE_IN_LABELS, _is_master, _load_accounts, _parse_date

KIND_TRANSACTION = "transaction"
KIND_ACCOUNT = "account"
COLLECTING = "collecting"
AWAITING = "awaiting_confirmation"

SUGGESTION_LIMIT = 5
MAX_AMOUNT = 1_000_000_000_000
MIN_DATE = date_cls(2000, 1, 1)
MAX_FUTURE_DAYS = 366


@dataclass
class ToolContext:
    conversation_id: str
    request_id: str
    question: str = ""
    today: date_cls = None
    # (tool name, result) of every write that succeeded during this request, so the
    # server can still tell the user what was saved if the model call fails afterwards
    saved: list = field(default_factory=list)

    def __post_init__(self):
        if self.today is None:
            self.today = date_cls.today()


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

_AR_DIACRITICS = re.compile("[ً-ٰٟـ]")
_STOPWORDS = {
    "من", "الى", "في", "على", "عن", "مع", "او", "ثم", "هذا", "هذه", "شو", "ما", "بدي", "بدك", "لو",
    "the", "a", "an", "of", "to", "for", "and", "or", "in", "on", "by", "with", "is", "it", "i", "my",
    "record", "add", "new", "entry", "transaction", "قيد", "سجل", "اضف", "جديد", "حساب",
}


def _norm(text: Optional[str]) -> str:
    """Lower-cases and folds Arabic spelling variants so 'المصاريف' / 'مصاريف' /
    'الإيجار' / 'ايجار' compare equal enough for keyword matching."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).lower()
    t = _AR_DIACRITICS.sub("", t)
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        t = t.replace(src, dst)
    return t


def _strip_al(word: str) -> str:
    return word[2:] if word.startswith("ال") and len(word) > 4 else word


def _tokens(*texts) -> list[str]:
    out = []
    for text in texts:
        for w in re.findall(r"\w+", _norm(text)):
            w = _strip_al(w)
            if len(w) >= 2 and w not in _STOPWORDS and not w.isdigit():
                out.append(w)
    return out


def _match_score(account_name: str, tokens: list[str]) -> int:
    name = _norm(account_name)
    words = [_strip_al(w) for w in re.findall(r"\w+", name)]
    score = 0
    for t in set(tokens):
        if t in name or any(len(w) >= 3 and (w in t) for w in words):
            score += 1
    return score


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _account_view(acc: Optional[Accounts]) -> Optional[dict]:
    if acc is None:
        return None
    return {"id": acc.id, "code": acc.code, "name": acc.name}


def _path(acc_id: int, accounts_by_id: dict) -> str:
    parts, seen = [], set()
    cur = accounts_by_id.get(acc_id)
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        parts.append(f"{cur.code + ' ' if cur.code else ''}{cur.name}")
        cur = accounts_by_id.get(cur.parentAccount) if cur.parentAccount is not None else None
    return " > ".join(reversed(parts))


def _as_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"\s*\d+\s*", value):
        return int(value)
    return None


def _as_amount(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 2)


def _err(field: str, code: str, message: str, **extra) -> dict:
    return {"field": field, "code": code, "message": message, **extra}


# ---------------------------------------------------------------------------
# draft + attachment storage
# ---------------------------------------------------------------------------

def get_draft(db: Session, conversation_id: str, kind: str) -> Optional[RimaDraft]:
    return (
        db.query(RimaDraft)
        .filter(RimaDraft.conversation_id == conversation_id, RimaDraft.kind == kind)
        .first()
    )


def _payload(draft: Optional[RimaDraft]) -> dict:
    if draft is None:
        return {}
    try:
        return json.loads(draft.payload or "{}")
    except ValueError:
        return {}


def _store(db: Session, conversation_id: str, kind: str, payload: dict, status: str, request_id: Optional[str]) -> RimaDraft:
    draft = get_draft(db, conversation_id, kind)
    now = datetime.utcnow()
    if draft is None:
        draft = RimaDraft(conversation_id=conversation_id, kind=kind, created_at=now)
        db.add(draft)
    draft.payload = _json(payload)
    draft.status = status
    draft.confirm_request_id = request_id if status == AWAITING else None
    draft.updated_at = now
    db.commit()
    return draft


def _delete_draft(db: Session, conversation_id: str, kind: str) -> None:
    draft = get_draft(db, conversation_id, kind)
    if draft is not None:
        db.delete(draft)
        db.commit()


def latest_attachment(db: Session, conversation_id: str) -> Optional[RimaAttachment]:
    return (
        db.query(RimaAttachment)
        .filter(RimaAttachment.conversation_id == conversation_id)
        .order_by(RimaAttachment.id.desc())
        .first()
    )


def _facts(att: Optional[RimaAttachment]) -> dict:
    if att is None:
        return {}
    try:
        return json.loads(att.facts or "{}")
    except ValueError:
        return {}


# ---------------------------------------------------------------------------
# suggestions
# ---------------------------------------------------------------------------

def _history_counts(db: Session, role: str, anchor_id: Optional[int]) -> Counter:
    """How often each account sits on `role` side ('debit'/'credit') of past
    entries; when `anchor_id` is given, only entries where the anchor account is
    on the OPPOSITE side (i.e. accounts that were actually paired with it)."""
    rows = (
        db.query(TransactionsDetail.idMaster, TransactionsDetail.acc_id, TransactionsDetail.debit, TransactionsDetail.credit)
        .order_by(TransactionsDetail.idMaster.desc())
        .limit(5000)
        .all()
    )
    by_master: dict[int, list] = {}
    for master_id, acc_id, debit, credit in rows:
        by_master.setdefault(master_id, []).append((acc_id, debit or 0, credit or 0))
    counts: Counter = Counter()
    for lines in by_master.values():
        if anchor_id is not None:
            opposite = (lambda d, c: d > 0) if role == "credit" else (lambda d, c: c > 0)
            if not any(acc == anchor_id and opposite(d, c) for acc, d, c in lines):
                continue
        for acc, d, c in lines:
            if acc == anchor_id:
                continue
            if (role == "debit" and d > 0) or (role == "credit" and c > 0):
                counts[acc] += 1
    return counts


def suggest_transaction_accounts(
    db: Session,
    role: str,
    ctx: ToolContext,
    search_terms: Optional[list],
    facts: dict,
    exclude_ids: set,
    anchor_id: Optional[int] = None,
    limit: int = SUGGESTION_LIMIT,
) -> list[dict]:
    """Book accounts ranked: document facts first, then the user's request,
    then history (accounts paired with the anchor account, else most used)."""
    accounts_by_id, children_map = _load_accounts(db)
    book = [a for a in accounts_by_id.values() if not _is_master(a.id, children_map) and a.id not in exclude_ids]

    doc_tokens = _tokens(
        facts.get("vendor"),
        facts.get("document_type"),
        *[i.get("description") for i in facts.get("items", []) if isinstance(i, dict)],
    )
    term_tokens = _tokens(*(search_terms or []))
    question_tokens = _tokens(ctx.question)
    history = _history_counts(db, role, anchor_id)

    scored = []
    for a in book:
        d = _match_score(a.name, doc_tokens)
        t = _match_score(a.name, term_tokens)
        q = _match_score(a.name, question_tokens)
        h = history.get(a.id, 0)
        if d:
            tier, reason = 0, "document"
        elif t or q:
            tier, reason = 1, "request"
        elif h:
            tier = 2
            reason = "history:paired" if anchor_id is not None else "history:frequent"
        else:
            tier, reason = 3, "other"
        scored.append((tier, -(d * 100 + t * 10 + q * 5 + h), a.code is None, a.code or "", a, reason))
    scored.sort(key=lambda s: s[:4])

    # a "history" boost also applies inside the request tier, already reflected in the sort key via h
    out = []
    for _, _, _, _, a, reason in scored[:limit]:
        out.append({"id": a.id, "code": a.code, "name": a.name, "path": _path(a.id, accounts_by_id), "reason": reason})
    return out


def _allowed_parent(acc: Accounts, children_map: dict, posted_ids: set) -> bool:
    """A parent must be a master account, or an account nothing has been posted
    to (it becomes a header when it gets its first child)."""
    return _is_master(acc.id, children_map) or acc.id not in posted_ids


def _posted_account_ids(db: Session) -> set:
    return {row[0] for row in db.query(TransactionsDetail.acc_id).distinct().all() if row[0] is not None}


def suggest_parents(db: Session, ctx: ToolContext, name: Optional[str], search_terms, facts: dict, limit: int = 6) -> list[dict]:
    accounts_by_id, children_map = _load_accounts(db)
    posted = _posted_account_ids(db)
    candidates = [a for a in accounts_by_id.values() if a.code and _allowed_parent(a, children_map, posted)]
    tokens_doc = _tokens(facts.get("vendor"), *[i.get("description") for i in facts.get("items", []) if isinstance(i, dict)])
    tokens_req = _tokens(name, *(search_terms or []), ctx.question)
    scored = []
    for a in candidates:
        d, r = _match_score(a.name, tokens_doc), _match_score(a.name, tokens_req)
        master = _is_master(a.id, children_map)
        scored.append((0 if d else 1 if r else 2, -(d * 10 + r), 0 if master else 1, a.code or "", a))
    scored.sort(key=lambda s: s[:4])
    return [
        {
            "id": a.id,
            "code": a.code,
            "name": a.name,
            "path": _path(a.id, accounts_by_id),
            "closeIn": a.closeIn,
            "closeIn_label": CLOSE_IN_LABELS.get(a.closeIn, a.closeIn),
            "reason": {0: "document", 1: "request", 2: "other"}[tier],
        }
        for tier, _, _, _, a in scored[:limit]
    ]


# ---------------------------------------------------------------------------
# account codes
# ---------------------------------------------------------------------------

def next_child_code(db: Session, parent: Accounts) -> Optional[str]:
    """Hierarchical scheme: a child's code is the parent's code plus two digits
    (001 -> 00101 -> 0010101). Default = highest existing child suffix + 1; if
    that overflows past 99, the lowest unused suffix; None when the parent has
    no code or all 99 slots are used."""
    if not parent.code:
        return None
    width = len(parent.code) + 2
    used = set()
    for (code,) in db.query(Accounts.code).filter(Accounts.code.isnot(None)).all():
        if code and len(code) == width and code.startswith(parent.code) and code[len(parent.code):].isdigit():
            used.add(int(code[len(parent.code):]))
    nxt = (max(used) + 1) if used else 1
    if nxt > 99:
        free = [n for n in range(1, 100) if n not in used]
        if not free:
            return None
        nxt = free[0]
    return f"{parent.code}{nxt:02d}"


def _validate_code(db: Session, code: str, parent: Accounts) -> Optional[dict]:
    code = (code or "").strip()
    if not code.isdigit():
        return _err("code", "invalid_code", "The code must contain digits only.")
    if parent.code:
        if not code.startswith(parent.code) or len(code) != len(parent.code) + 2 or int(code[len(parent.code):]) == 0:
            return _err(
                "code", "code_scheme",
                f"A child of {parent.code} must be {parent.code} followed by two digits (01-99), e.g. {next_child_code(db, parent) or parent.code + '01'}.",
            )
    if db.query(Accounts).filter(Accounts.code == code).first() is not None:
        return _err("code", "code_taken", f"The code {code} is already used by another account.")
    return None


# ---------------------------------------------------------------------------
# transaction draft
# ---------------------------------------------------------------------------

def _tx_view(db: Session, p: dict, accounts_by_id: dict) -> dict:
    return {
        "debit_account": _account_view(accounts_by_id.get(p.get("debit_acc_id"))),
        "credit_account": _account_view(accounts_by_id.get(p.get("credit_acc_id"))),
        "amount": p.get("amount"),
        "date": p.get("date"),
        "date_source": p.get("date_source"),
        "description": p.get("description"),
        "document_attached": bool(p.get("attachment_id")),
    }


def _tx_next_step(p: dict) -> str:
    if not p.get("debit_acc_id"):
        return "debit_account"
    if not p.get("credit_acc_id"):
        return "credit_account"
    if p.get("amount") is None:
        return "amount"
    return "confirmation"


def _validate_book_account(db: Session, field: str, value, accounts_by_id: dict, children_map: dict) -> tuple[Optional[int], Optional[dict]]:
    acc_id = _as_int(value)
    if acc_id is None or acc_id not in accounts_by_id:
        return None, _err(field, "not_found", "No account with that id exists. Pick one from the suggestions or the chart of accounts.")
    if _is_master(acc_id, children_map):
        kids = [
            {"id": c, "code": accounts_by_id[c].code, "name": accounts_by_id[c].name}
            for c in children_map.get(acc_id, [])
        ]
        return None, _err(
            field, "master_account",
            "That is a master (header) account and cannot be used in an entry. Ask the user to pick one of its detail accounts.",
            children=kids,
        )
    return acc_id, None


def _validate_date(value, today: date_cls) -> tuple[Optional[str], Optional[dict]]:
    try:
        d = _parse_date(value)
    except (ValueError, TypeError):
        return None, _err("date", "invalid_date", "Use a real date in YYYY-MM-DD form.")
    if d is None:
        return None, _err("date", "invalid_date", "Use a real date in YYYY-MM-DD form.")
    d = d.date()
    if d < MIN_DATE or d > today + timedelta(days=MAX_FUTURE_DAYS):
        return None, _err("date", "date_out_of_range", "That date is outside the accepted range.")
    return d.isoformat(), None


_TX_DIRECTIVES = {
    "debit_account": (
        "Ask ONLY for the DEBIT account now. Show the numbered suggestions (name and code, never the internal id) and "
        "let the user pick one, name another account, or ask to add a new account. Ask nothing else in this message."
    ),
    "credit_account": (
        "The debit account is set. Ask ONLY for the CREDIT account now, showing the numbered suggestions (chosen for the "
        "debit account). The user may pick one, name another, or ask to add a new account. Ask nothing else."
    ),
    "amount": (
        "Ask ONLY for the amount. If suggested_amount is present, say it comes from the attached document and ask whether "
        "to use it. Do not assume it."
    ),
    "confirmation": (
        "The entry is complete. Read it back (debit account, credit account, amount, date and its source, whether a "
        "document is attached) and ask the user to confirm, change something, or cancel. Do NOT call commit_transaction "
        "in this same turn - wait for the user's next message."
    ),
}


def update_transaction_draft(
    db: Session,
    ctx: ToolContext,
    debit_account_id=None,
    credit_account_id=None,
    amount=None,
    date=None,
    description=None,
    search_terms=None,
) -> dict:
    accounts_by_id, children_map = _load_accounts(db)
    draft = get_draft(db, ctx.conversation_id, KIND_TRANSACTION)
    p = _payload(draft)
    was_status = draft.status if draft else None
    before = _json(p)
    errors: list[dict] = []
    att = latest_attachment(db, ctx.conversation_id)
    facts = _facts(att)

    if att is not None and not p.get("attachment_id"):
        p["attachment_id"] = att.id

    if debit_account_id is not None:
        acc, e = _validate_book_account(db, "debit_account_id", debit_account_id, accounts_by_id, children_map)
        if e:
            errors.append(e)
        elif acc == p.get("credit_acc_id"):
            errors.append(_err("debit_account_id", "same_account", "The debit and credit accounts must be different."))
        else:
            p["debit_acc_id"] = acc
    if credit_account_id is not None:
        acc, e = _validate_book_account(db, "credit_account_id", credit_account_id, accounts_by_id, children_map)
        if e:
            errors.append(e)
        elif acc == p.get("debit_acc_id"):
            errors.append(_err("credit_account_id", "same_account", "The debit and credit accounts must be different."))
        else:
            p["credit_acc_id"] = acc
    if amount is not None:
        value = _as_amount(amount)
        if value is None or value <= 0 or value > MAX_AMOUNT:
            errors.append(_err("amount", "invalid_amount", "The amount must be a positive number."))
        else:
            p["amount"] = value
    if date is not None:
        iso, e = _validate_date(date, ctx.today)
        if e:
            errors.append(e)
        else:
            p["date"], p["date_source"] = iso, "user"
    if description is not None and str(description).strip():
        p["description"] = str(description).strip()[:200]

    if not p.get("date"):
        doc_date, e = _validate_date(facts.get("date"), ctx.today) if facts.get("date") else (None, True)
        if doc_date and not e:
            p["date"], p["date_source"] = doc_date, "document"
        else:
            p["date"], p["date_source"] = ctx.today.isoformat(), "today"

    step = _tx_next_step(p)
    changed = _json(p) != before
    if step == "confirmation":
        if draft is None or was_status != AWAITING or changed:
            status, request_id = AWAITING, ctx.request_id
        else:
            status, request_id = AWAITING, draft.confirm_request_id
    else:
        status, request_id = COLLECTING, None
    _store(db, ctx.conversation_id, KIND_TRANSACTION, p, status, request_id)

    result = {
        "status": status,
        "next_step": step,
        "must_do": _TX_DIRECTIVES[step],
        "draft": _tx_view(db, p, accounts_by_id),
        "errors": errors,
    }
    terms = search_terms if isinstance(search_terms, list) else ([search_terms] if search_terms else [])
    if step == "debit_account":
        result["suggestions"] = suggest_transaction_accounts(
            db, "debit", ctx, terms, facts, exclude_ids={p.get("credit_acc_id")} - {None}, anchor_id=p.get("credit_acc_id")
        )
    elif step == "credit_account":
        result["suggestions"] = suggest_transaction_accounts(
            db, "credit", ctx, terms, facts, exclude_ids={p["debit_acc_id"]}, anchor_id=p["debit_acc_id"]
        )
    if att is not None:
        result["document_facts"] = facts
        total = _as_amount(facts.get("total"))
        if step == "amount" and total:
            result["suggested_amount"] = {"value": total, "source": "document", "currency": facts.get("currency")}
        if p.get("amount") is not None and total and abs(p["amount"] - total) > 0.005:
            result["notes"] = [f"The amount differs from the document total ({total}). Mention this when reading the entry back."]
    return result


def _commit_transaction_draft(db: Session, draft: RimaDraft, today: date_cls) -> dict:
    """Re-validates the whole draft and writes the entry (+ its document) in one DB
    transaction. Callers have already checked confirmation."""
    p = _payload(draft)
    accounts_by_id, children_map = _load_accounts(db)
    problems = []
    debit, e = _validate_book_account(db, "debit_account_id", p.get("debit_acc_id"), accounts_by_id, children_map)
    problems += [e] if e else []
    credit, e = _validate_book_account(db, "credit_account_id", p.get("credit_acc_id"), accounts_by_id, children_map)
    problems += [e] if e else []
    amt = _as_amount(p.get("amount"))
    if amt is None or amt <= 0:
        problems.append(_err("amount", "invalid_amount", "The amount must be a positive number."))
    iso, e = _validate_date(p.get("date"), today)
    problems += [e] if e else []
    if not problems and debit == credit:
        problems.append(_err("credit_account_id", "same_account", "The debit and credit accounts must be different."))
    if problems:
        return {"ok": False, "error": "invalid_draft", "errors": problems}

    description = p.get("description") or f"{accounts_by_id[debit].name} / {accounts_by_id[credit].name}"
    master = TransactionsMaster(
        date=datetime.combine(date_cls.fromisoformat(iso), datetime.min.time()),
        notes=description,
    )
    master.rsTransactionsMaster.append(TransactionsDetail(debit=amt, credit=0, acc_id=debit, description=description))
    master.rsTransactionsMaster.append(TransactionsDetail(debit=0, credit=amt, acc_id=credit, description=description))

    att = db.get(RimaAttachment, p["attachment_id"]) if p.get("attachment_id") else None
    if att is not None:
        master.document, master.document_mime, master.document_name = att.data, att.mime, att.filename
    try:
        db.add(master)
        if att is not None:
            db.delete(att)
        db.delete(draft)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "ok": True,
        "transaction_id": master.id,
        "date": iso,
        "amount": amt,
        "debit_account": _account_view(accounts_by_id[debit]),
        "credit_account": _account_view(accounts_by_id[credit]),
        "document_saved": att is not None,
    }


def commit_transaction(db: Session, ctx: ToolContext) -> dict:
    draft = get_draft(db, ctx.conversation_id, KIND_TRANSACTION)
    if draft is None:
        return {"ok": False, "error": "no_draft", "message": "There is no transaction draft to save."}
    if draft.status != AWAITING:
        step = _tx_next_step(_payload(draft))
        return {
            "ok": False, "error": "incomplete", "next_step": step, "must_do": _TX_DIRECTIVES[step],
            "message": "The draft is not complete yet; nothing was saved.",
        }
    if draft.confirm_request_id == ctx.request_id:
        return {
            "ok": False, "error": "needs_user_confirmation", "must_do": _TX_DIRECTIVES["confirmation"],
            "message": "The user has not confirmed yet. Read the entry back and wait for their next message.",
        }
    return _commit_transaction_draft(db, draft, ctx.today)


def cancel_transaction_draft(db: Session, ctx: ToolContext) -> dict:
    return _cancel(db, ctx.conversation_id, KIND_TRANSACTION)


def _cancel(db: Session, conversation_id: str, kind: str) -> dict:
    draft = get_draft(db, conversation_id, kind)
    if draft is None:
        return {"ok": True, "cancelled": False, "message": "There was nothing to cancel."}
    p = _payload(draft)
    if kind == KIND_TRANSACTION and p.get("attachment_id"):
        att = db.get(RimaAttachment, p["attachment_id"])
        if att is not None:
            db.delete(att)
    db.delete(draft)
    db.commit()
    return {"ok": True, "cancelled": True}


# ---------------------------------------------------------------------------
# account draft
# ---------------------------------------------------------------------------

_CLOSE_IN_INPUT = {
    "0": 0, "1": 1, "2": 2,
    "balance sheet": 0, "balancesheet": 0, "الميزانيه العموميه": 0, "ميزانيه عموميه": 0, "الميزانيه": 0,
    "p&l": 1, "pl": 1, "profit and loss": 1, "profit & loss": 1, "ارباح وخسائر": 1, "الارباح والخسائر": 1,
    "trading": 2, "متاجره": 2, "المتاجره": 2,
}


def _as_close_in(value) -> Optional[int]:
    n = _as_int(value)
    if n in (0, 1, 2):
        return n
    if isinstance(value, str):
        return _CLOSE_IN_INPUT.get(_norm(value).strip())
    return None


def _acct_view(db: Session, p: dict, accounts_by_id: dict) -> dict:
    parent = accounts_by_id.get(p.get("parent_id"))
    return {
        "name": p.get("name"),
        "parent_account": {**_account_view(parent), "path": _path(parent.id, accounts_by_id)} if parent else None,
        "close_in": p.get("close_in"),
        "close_in_label": CLOSE_IN_LABELS.get(p.get("close_in")) if p.get("close_in") is not None else None,
        "code": p.get("code"),
        "for_slot": p.get("for_slot"),
    }


def _acct_next_step(p: dict, parent: Optional[Accounts]) -> str:
    if not p.get("name"):
        return "name"
    if not p.get("parent_id"):
        return "parent_account"
    if p.get("close_in") is None:
        return "close_in"
    if p.get("code") is None and parent is not None and parent.code:
        return "code"
    return "confirmation"


_ACCT_DIRECTIVES = {
    "name": "Ask ONLY for the new account's name.",
    "parent_account": (
        "Ask ONLY for the parent (father) account. Show the numbered suggestions with their paths. A new account cannot "
        "be a top-level account, and the parent must be a header account or one with no postings."
    ),
    "close_in": (
        "Ask ONLY where the account closes: Balance Sheet, P&L (profit and loss) or Trading. The parent's setting is "
        "suggested (see suggested_close_in) but the user must choose."
    ),
    "code": (
        "Ask ONLY about the account code: propose suggested_code as the default and let the user accept it or give "
        "another code (parent code + two digits)."
    ),
    "confirmation": (
        "The account is complete. Read it back (name, parent with its path, closing type, code) and ask the user to "
        "confirm, change something, or cancel. Do NOT call commit_account in this same turn. Say it will be a detail "
        "(postable) account."
    ),
}


def update_account_draft(
    db: Session,
    ctx: ToolContext,
    name=None,
    parent_account_id=None,
    close_in=None,
    code=None,
    for_slot=None,
    search_terms=None,
) -> dict:
    accounts_by_id, children_map = _load_accounts(db)
    posted = _posted_account_ids(db)
    draft = get_draft(db, ctx.conversation_id, KIND_ACCOUNT)
    p = _payload(draft)
    was_status = draft.status if draft else None
    before = _json(p)
    errors: list[dict] = []
    att = latest_attachment(db, ctx.conversation_id)
    facts = _facts(att)

    if for_slot in ("debit", "credit"):
        p["for_slot"] = for_slot
    if name is not None:
        clean = re.sub(r"\s+", " ", str(name)).strip()
        if not clean:
            errors.append(_err("name", "empty_name", "The account name cannot be empty."))
        else:
            p["name"] = clean[:120]
    if parent_account_id is not None:
        pid = _as_int(parent_account_id)
        parent = accounts_by_id.get(pid) if pid is not None else None
        if parent is None:
            errors.append(_err("parent_account_id", "not_found", "No account with that id exists."))
        elif not _allowed_parent(parent, children_map, posted):
            errors.append(_err(
                "parent_account_id", "parent_has_postings",
                "That account already has transactions posted to it and no sub-accounts, so it cannot become a parent. "
                "Pick a header account, or an account with no postings.",
            ))
        else:
            if p.get("parent_id") != parent.id:
                p["code"] = None  # a code chosen under another parent no longer fits
            p["parent_id"] = parent.id
    if close_in is not None:
        ci = _as_close_in(close_in)
        if ci is None:
            errors.append(_err("close_in", "invalid_close_in", "Closing type must be Balance Sheet (0), P&L (1) or Trading (2)."))
        else:
            p["close_in"] = ci

    parent = accounts_by_id.get(p.get("parent_id"))
    if code is not None:
        if parent is None:
            errors.append(_err("code", "parent_first", "Choose the parent account before the code."))
        else:
            e = _validate_code(db, str(code), parent)
            if e:
                errors.append(e)
            else:
                p["code"] = str(code).strip()

    # a name that duplicates a sibling is refused as soon as both are known
    if p.get("name") and parent is not None:
        dup = any(
            a.parentAccount == parent.id and _norm(a.name).strip() == _norm(p["name"]).strip()
            for a in accounts_by_id.values()
        )
        if dup:
            errors.append(_err("name", "duplicate_name", f"An account named '{p['name']}' already exists under {parent.name}."))
            p.pop("name", None)

    step = _acct_next_step(p, parent)
    default_code = next_child_code(db, parent) if parent is not None else None
    if parent is not None and parent.code and default_code is None and p.get("code") is None:
        errors.append(_err("parent_account_id", "parent_full", "All 99 code slots under this parent are used. Pick another parent."))
        p.pop("parent_id", None)
        parent = None
        step = _acct_next_step(p, None)

    changed = _json(p) != before
    if step == "confirmation":
        status = AWAITING
        request_id = ctx.request_id if (draft is None or was_status != AWAITING or changed) else draft.confirm_request_id
    else:
        status, request_id = COLLECTING, None
    _store(db, ctx.conversation_id, KIND_ACCOUNT, p, status, request_id)

    result = {
        "status": status,
        "next_step": step,
        "must_do": _ACCT_DIRECTIVES[step],
        "draft": _acct_view(db, p, accounts_by_id),
        "errors": errors,
    }
    terms = search_terms if isinstance(search_terms, list) else ([search_terms] if search_terms else [])
    if step == "parent_account":
        result["suggestions"] = suggest_parents(db, ctx, p.get("name"), terms, facts)
    if step == "close_in":
        result["options"] = [{"value": k, "label": v} for k, v in CLOSE_IN_LABELS.items()]
        result["suggested_close_in"] = {"value": parent.closeIn, "label": CLOSE_IN_LABELS.get(parent.closeIn)} if parent else None
    if step == "code":
        result["suggested_code"] = default_code
    if parent is not None and not parent.code:
        result["notes"] = ["The parent has no code, so no code is suggested; the account will be created without one unless the user gives a unique numeric code."]
    return result


def _commit_account_draft(db: Session, draft: RimaDraft, ctx_request_id: Optional[str] = None) -> dict:
    p = _payload(draft)
    accounts_by_id, children_map = _load_accounts(db)
    posted = _posted_account_ids(db)
    problems = []
    parent = accounts_by_id.get(p.get("parent_id"))
    if not p.get("name"):
        problems.append(_err("name", "empty_name", "The account name is required."))
    if parent is None:
        problems.append(_err("parent_account_id", "not_found", "A parent account is required."))
    elif not _allowed_parent(parent, children_map, posted):
        problems.append(_err("parent_account_id", "parent_has_postings", "That parent now has postings and cannot take children."))
    if p.get("close_in") not in (0, 1, 2):
        problems.append(_err("close_in", "invalid_close_in", "The closing type is required."))
    code = p.get("code")
    if parent is not None:
        if code is None and parent.code:
            problems.append(_err("code", "code_required", "A code is required."))
        elif code is not None:
            e = _validate_code(db, code, parent)
            problems += [e] if e else []
        if p.get("name") and any(
            a.parentAccount == parent.id and _norm(a.name).strip() == _norm(p["name"]).strip() for a in accounts_by_id.values()
        ):
            problems.append(_err("name", "duplicate_name", "A sibling account already has this name."))
    if problems:
        return {"ok": False, "error": "invalid_draft", "errors": problems}

    account = Accounts(code=code, name=p["name"], closeIn=p["close_in"], parentAccount=parent.id)
    try:
        db.add(account)
        db.flush()
        follow_up = None
        slot = p.get("for_slot")
        tx_draft = get_draft(db, draft.conversation_id, KIND_TRANSACTION) if slot in ("debit", "credit") else None
        if tx_draft is not None:
            tp = _payload(tx_draft)
            other = tp.get("credit_acc_id" if slot == "debit" else "debit_acc_id")
            if other != account.id:
                tp["debit_acc_id" if slot == "debit" else "credit_acc_id"] = account.id
            step = _tx_next_step(tp)
            tx_draft.payload = _json(tp)
            tx_draft.updated_at = datetime.utcnow()
            if step == "confirmation":
                tx_draft.status, tx_draft.confirm_request_id = AWAITING, ctx_request_id or "button"
            else:
                tx_draft.status, tx_draft.confirm_request_id = COLLECTING, None
            follow_up = {"transaction_next_step": step, "must_do": _TX_DIRECTIVES[step]}
        db.delete(draft)
        db.commit()
    except Exception:
        db.rollback()
        raise
    result = {
        "ok": True,
        "account": {"id": account.id, "code": account.code, "name": account.name, "closeIn": CLOSE_IN_LABELS.get(account.closeIn), "parent": parent.name},
    }
    if follow_up:
        result["transaction_draft"] = follow_up
    return result


def commit_account(db: Session, ctx: ToolContext) -> dict:
    draft = get_draft(db, ctx.conversation_id, KIND_ACCOUNT)
    if draft is None:
        return {"ok": False, "error": "no_draft", "message": "There is no account draft to save."}
    if draft.status != AWAITING:
        parent = db.get(Accounts, _payload(draft).get("parent_id")) if _payload(draft).get("parent_id") else None
        step = _acct_next_step(_payload(draft), parent)
        return {"ok": False, "error": "incomplete", "next_step": step, "must_do": _ACCT_DIRECTIVES[step],
                "message": "The account draft is not complete yet; nothing was created."}
    if draft.confirm_request_id == ctx.request_id:
        return {"ok": False, "error": "needs_user_confirmation", "must_do": _ACCT_DIRECTIVES["confirmation"],
                "message": "The user has not confirmed yet. Read the account back and wait for their next message."}
    return _commit_account_draft(db, draft, ctx.request_id)


def cancel_account_draft(db: Session, ctx: ToolContext) -> dict:
    return _cancel(db, ctx.conversation_id, KIND_ACCOUNT)


# ---------------------------------------------------------------------------
# pending drafts: shared by the prompt, the API response and the /drafts routes
# ---------------------------------------------------------------------------

def describe_draft(db: Session, draft: RimaDraft) -> dict:
    accounts_by_id, _ = _load_accounts(db)
    p = _payload(draft)
    if draft.kind == KIND_TRANSACTION:
        view, step = _tx_view(db, p, accounts_by_id), _tx_next_step(p)
    else:
        parent = accounts_by_id.get(p.get("parent_id"))
        view, step = _acct_view(db, p, accounts_by_id), _acct_next_step(p, parent)
    return {
        "kind": draft.kind,
        "status": draft.status,
        "next_step": step,
        "ready_to_confirm": draft.status == AWAITING,
        "draft": view,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def list_pending_drafts(db: Session, conversation_id: str) -> list[dict]:
    rows = db.query(RimaDraft).filter(RimaDraft.conversation_id == conversation_id).order_by(RimaDraft.id).all()
    return [describe_draft(db, d) for d in rows]


def confirm_draft(db: Session, conversation_id: str, kind: str, today: Optional[date_cls] = None) -> dict:
    """A user pressing "confirm": saves exactly what the draft says, but only if
    it is complete and already read back (awaiting_confirmation)."""
    draft = get_draft(db, conversation_id, kind)
    if draft is None:
        return {"ok": False, "error": "no_draft"}
    if draft.status != AWAITING:
        return {"ok": False, "error": "incomplete", "next_step": describe_draft(db, draft)["next_step"]}
    if kind == KIND_TRANSACTION:
        return _commit_transaction_draft(db, draft, today or date_cls.today())
    return _commit_account_draft(db, draft)


def cancel_draft(db: Session, conversation_id: str, kind: str) -> dict:
    return _cancel(db, conversation_id, kind)


def pending_drafts_prompt(db: Session, conversation_id: str) -> str:
    """Server-authored block appended to the system instruction each turn, so the
    reminder duty doesn't depend on the model remembering earlier turns."""
    pending = list_pending_drafts(db, conversation_id)
    if not pending:
        return ""
    lines = [
        "",
        "عمليات غير محفوظة (حالة من الخادم، وهي المرجع وليست ذاكرة المحادثة):",
    ]
    for d in pending:
        lines.append(f"- {d['kind']}: الحالة={d['status']}، الخطوة التالية={d['next_step']}، المسودة={_json(d['draft'])}")
    lines.append(
        "قاعدة إلزامية: إذا كانت رسالة المستخدم الحالية لا تتعلق بهذه المسودة، أجيبي عنها أولاً ثم ذكّريه بوضوح بأن لديه "
        "عملية غير محفوظة وله ثلاثة خيارات: التأكيد (حفظها كما هي)، أو التعديل (يعطيك المعلومات من جديد)، أو الإلغاء. "
        "لا تحفظي ولا تلغي أي مسودة إلا بطلب صريح من المستخدم."
    )
    return "\n".join(lines)


def saved_summary(saved: list) -> str:
    """Plain, model-free confirmation of what this request wrote to the books."""
    lines = []
    for name, r in saved:
        if name == "commit_transaction":
            lines.append(
                f"تم حفظ القيد رقم {r['transaction_id']}: مدين {r['debit_account']['name']} / دائن {r['credit_account']['name']} "
                f"بمبلغ {r['amount']:g} بتاريخ {r['date']}" + (" (مع المستند المرفق)." if r.get("document_saved") else ".")
            )
        elif name == "commit_account":
            a = r["account"]
            lines.append(f"تم إنشاء الحساب {(a['code'] + ' - ') if a.get('code') else ''}{a['name']} تحت {a['parent']}.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# tool declarations (what the model sees) and registry
# ---------------------------------------------------------------------------

DRAFT_TOOL_DECLARATIONS = [
    {
        "name": "update_transaction_draft",
        "description": (
            "Starts or updates the DRAFT of a new accounting entry (one debit account, one credit account, one amount). "
            "Pass ONLY what the user has actually said or clearly chosen - never guess an id or an amount. The server "
            "validates each field, tells you the single next_step to ask about (debit_account, then credit_account, then "
            "amount, then confirmation) and returns ranked suggestions. Follow must_do exactly. Nothing is saved by this "
            "tool. Date defaults to today (or the attached document's date). Call it with no arguments to start the flow "
            "or to re-read the state."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "debit_account_id": {"type": "integer", "description": "Detail account id chosen by the user for the debit side."},
                "credit_account_id": {"type": "integer", "description": "Detail account id chosen by the user for the credit side."},
                "amount": {"type": "number", "description": "Positive amount stated by the user (or confirmed from the document)."},
                "date": {"type": "string", "description": "YYYY-MM-DD, only if the user gave a date. Resolve words like 'yesterday' from today's date."},
                "description": {"type": "string", "description": "Short description of the entry, derived from the request. Optional."},
                "search_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords about what the user is doing, TRANSLATED into the language of the account names (e.g. Arabic), used only to rank suggestions.",
                },
            },
        },
    },
    {
        "name": "commit_transaction",
        "description": (
            "Saves the drafted entry. Only allowed when the draft is complete AND the user confirmed it in a message AFTER "
            "you read it back; otherwise the server refuses. Call it only when the user has clearly said yes/confirm."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_transaction_draft",
        "description": "Discards the entry draft (and its attached document) when the user asks to cancel/abort.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "update_account_draft",
        "description": (
            "Starts or updates the DRAFT of a NEW account the user wants added because the one they need doesn't exist. "
            "Pass ONLY what the user actually said. Required: name, parent account (never a top-level account), and where "
            "it closes (0 Balance Sheet, 1 P&L, 2 Trading). The server suggests the code (parent code + next two digits) "
            "and tells you the single next_step to ask about. The new account is always a detail (postable) account. "
            "Follow must_do exactly. Nothing is created by this tool."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the new account."},
                "parent_account_id": {"type": "integer", "description": "Id of the parent (father) account chosen by the user."},
                "close_in": {"type": "integer", "description": "0 = Balance Sheet, 1 = P&L, 2 = Trading, chosen by the user."},
                "code": {"type": "string", "description": "Account code, only once the user accepted the suggested one or gave their own."},
                "for_slot": {
                    "type": "string",
                    "enum": ["debit", "credit"],
                    "description": "Set when the account is being created in the middle of an entry, for that side of the entry.",
                },
                "search_terms": {"type": "array", "items": {"type": "string"}, "description": "Keywords (in the account names' language) to rank parent suggestions."},
            },
        },
    },
    {
        "name": "commit_account",
        "description": (
            "Creates the drafted account. Only allowed when the draft is complete AND the user confirmed it in a message "
            "AFTER you read it back; otherwise the server refuses."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_account_draft",
        "description": "Discards the new-account draft when the user asks to cancel/abort.",
        "parameters": {"type": "object", "properties": {}},
    },
]

DRAFT_TOOL_FUNCTIONS = {
    "update_transaction_draft": update_transaction_draft,
    "commit_transaction": commit_transaction,
    "cancel_transaction_draft": cancel_transaction_draft,
    "update_account_draft": update_account_draft,
    "commit_account": commit_account,
    "cancel_account_draft": cancel_account_draft,
}

# tools that receive the injected ToolContext as their second argument
CONTEXT_TOOLS = set(DRAFT_TOOL_FUNCTIONS)
