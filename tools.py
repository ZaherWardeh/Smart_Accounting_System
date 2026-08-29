"""Domain-shaped tools for the LangGraph agent_loop.

Each function is a plain, independently testable Python function against the
DB — no LLM, no LangGraph. They mirror how an accountant actually reasons:
chart -> ledger -> balance.
"""

from datetime import datetime, date as date_cls
from typing import Optional, Union

from sqlalchemy.orm import Session, joinedload

from models import Accounts, TransactionsDetail, TransactionsMaster

CLOSE_IN_LABELS = {0: "Balance Sheet", 1: "P&L", 2: "Trading"}

DateLike = Union[str, date_cls, datetime, None]


def _parse_date(value: DateLike, end_of_day: bool = False) -> Optional[datetime]:
    """Parses a date-ish value into a datetime. Bare dates (no time component)
    used as an upper bound get pushed to the end of that day so same-day
    transactions aren't excluded."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date_cls):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        dt = None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            raise ValueError(f"Unrecognized date format: {value!r}")
    else:
        raise TypeError(f"Unsupported date type: {type(value)!r}")

    if end_of_day and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        dt = dt.replace(hour=23, minute=59, second=59)
    return dt


def _load_accounts(db: Session):
    """Returns (accounts_by_id, children_map). children_map maps a parent
    account id to the list of its direct child account ids; an id appearing
    as a key in children_map is a "master" account, otherwise it's a "book"
    account."""
    accounts = db.query(Accounts).all()
    accounts_by_id = {a.id: a for a in accounts}
    children_map: dict[int, list[int]] = {}
    for a in accounts:
        if a.parentAccount is not None:
            children_map.setdefault(a.parentAccount, []).append(a.id)
    return accounts_by_id, children_map


def _is_master(acc_id: int, children_map: dict) -> bool:
    return acc_id in children_map


def _descendant_book_ids(acc_id: int, accounts_by_id: dict, children_map: dict) -> list[int]:
    """Resolves an account id to the list of leaf ("book") account ids
    underneath it. A book account resolves to itself. A master account
    resolves to every book account recursively underneath it — nothing
    should ever post directly to a header account, so the master's own id
    is never included."""
    if acc_id not in accounts_by_id:
        return []
    children = children_map.get(acc_id)
    if not children:
        return [acc_id]
    book_ids: list[int] = []
    for child_id in children:
        book_ids.extend(_descendant_book_ids(child_id, accounts_by_id, children_map))
    return book_ids


def get_chart_of_accounts(db: Session) -> list[dict]:
    """Returns every account: id, name, closeIn (labeled), parentAccount,
    and a derived account_type ("master" if any other account lists this
    one as its parentAccount, otherwise "book")."""
    accounts_by_id, children_map = _load_accounts(db)
    return [
        {
            "id": a.id,
            "name": a.name,
            "closeIn": CLOSE_IN_LABELS.get(a.closeIn, a.closeIn),
            "parentAccount": a.parentAccount,
            "account_type": "master" if _is_master(a.id, children_map) else "book",
        }
        for a in accounts_by_id.values()
    ]


def get_account_transactions(
    db: Session,
    acc_id: int,
    date_from: DateLike = None,
    date_to: DateLike = None,
) -> list[dict]:
    """Returns the transaction lines for that account in the given range
    (all-time if omitted). If acc_id is a master account, pulls transactions
    from every descendant book account underneath it too."""
    accounts_by_id, children_map = _load_accounts(db)
    if acc_id not in accounts_by_id:
        return []

    book_ids = _descendant_book_ids(acc_id, accounts_by_id, children_map)

    query = (
        db.query(TransactionsDetail)
        .options(joinedload(TransactionsDetail.rsTransactionsMaster))
        .filter(TransactionsDetail.acc_id.in_(book_ids))
    )

    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to, end_of_day=True)
    if parsed_from is not None:
        query = query.filter(TransactionsDetail.rsTransactionsMaster.has(TransactionsMaster.date >= parsed_from))
    if parsed_to is not None:
        query = query.filter(TransactionsDetail.rsTransactionsMaster.has(TransactionsMaster.date <= parsed_to))

    details = query.all()

    result = []
    for d in details:
        master = d.rsTransactionsMaster
        result.append(
            {
                "transaction_id": master.id if master else None,
                "date": master.date.strftime("%Y-%m-%d") if master and master.date else None,
                "debit": d.debit or 0,
                "credit": d.credit or 0,
                "description": d.description or (master.notes if master else None),
                "acc_id": d.acc_id,
                "acc_name": accounts_by_id[d.acc_id].name if d.acc_id in accounts_by_id else None,
            }
        )

    result.sort(key=lambda r: r["date"] or "")
    return result


def get_account_balance(
    db: Session,
    acc_ids: list[int],
    as_of_date: DateLike = None,
    date_from: DateLike = None,
    date_to: DateLike = None,
) -> dict:
    """Takes a list of account ids. Branches per account on its own closeIn:
    Balance Sheet accounts (closeIn=0) are cumulative as of as_of_date
    (defaults to today). P&L / Trading accounts (closeIn=1/2) are summed
    over date_from/date_to. Master accounts sum every descendant book
    account recursively. Returns a combined debit_sum/credit_sum/net across
    every id passed in, plus a per-account breakdown — the tool does not
    sign the net figure into "the balance is X"; that interpretation is
    left to answer synthesis."""
    accounts_by_id, children_map = _load_accounts(db)

    breakdown = []
    combined_debit = 0.0
    combined_credit = 0.0

    effective_as_of = _parse_date(as_of_date, end_of_day=True) or datetime.utcnow()
    parsed_from = _parse_date(date_from)
    parsed_to = _parse_date(date_to, end_of_day=True)

    for acc_id in acc_ids:
        account = accounts_by_id.get(acc_id)
        if account is None:
            breakdown.append({"acc_id": acc_id, "error": "Account not found"})
            continue

        book_ids = _descendant_book_ids(acc_id, accounts_by_id, children_map)
        query = db.query(TransactionsDetail).filter(TransactionsDetail.acc_id.in_(book_ids))

        if account.closeIn == 0:
            query = query.filter(TransactionsDetail.rsTransactionsMaster.has(TransactionsMaster.date <= effective_as_of))
            period = f"as of {effective_as_of.strftime('%Y-%m-%d')}"
        else:
            if parsed_from is not None:
                query = query.filter(TransactionsDetail.rsTransactionsMaster.has(TransactionsMaster.date >= parsed_from))
            if parsed_to is not None:
                query = query.filter(TransactionsDetail.rsTransactionsMaster.has(TransactionsMaster.date <= parsed_to))
            period = f"{date_from or 'inception'} to {date_to or 'latest'}"

        details = query.all()
        debit_sum = sum(d.debit or 0 for d in details)
        credit_sum = sum(d.credit or 0 for d in details)

        breakdown.append(
            {
                "acc_id": acc_id,
                "acc_name": account.name,
                "account_type": "master" if _is_master(acc_id, children_map) else "book",
                "closeIn": CLOSE_IN_LABELS.get(account.closeIn, account.closeIn),
                "resolved_book_accounts": [
                    {"id": bid, "name": accounts_by_id[bid].name} for bid in book_ids if bid in accounts_by_id
                ],
                "debit_sum": debit_sum,
                "credit_sum": credit_sum,
                "net": debit_sum - credit_sum,
                "period": period,
            }
        )
        combined_debit += debit_sum
        combined_credit += credit_sum

    return {
        "debit_sum": combined_debit,
        "credit_sum": combined_credit,
        "net": combined_debit - combined_credit,
        "breakdown": breakdown,
    }


# Provider-agnostic JSON-schema tool declarations, bound to the Gemini call
# inside agent_loop.
TOOL_DECLARATIONS = [
    {
        "name": "get_chart_of_accounts",
        "description": (
            "Returns every account in the chart of accounts: id, name, closeIn "
            "(Balance Sheet / P&L / Trading), parentAccount, and account_type "
            "(master = rollup header, book = postable leaf). Use this first to "
            "resolve an account name (e.g. 'sales' or 'الصندوق') to an id before "
            "calling get_account_transactions or get_account_balance."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_account_transactions",
        "description": (
            "Returns the transaction lines for one account in an optional date "
            "range (all-time if omitted). If acc_id is a master account, "
            "includes transactions from every descendant book account beneath it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "acc_id": {"type": "integer", "description": "Account id from get_chart_of_accounts."},
                "date_from": {"type": "string", "description": "Inclusive start date, YYYY-MM-DD. Optional."},
                "date_to": {"type": "string", "description": "Inclusive end date, YYYY-MM-DD. Optional."},
            },
            "required": ["acc_id"],
        },
    },
    {
        "name": "get_account_balance",
        "description": (
            "Returns the debit/credit/net balance for one or more accounts, plus "
            "a per-account breakdown. Pass multiple ids to aggregate related "
            "accounts (e.g. all cash/bank accounts for a 'liquidity' question). "
            "Balance Sheet accounts (closeIn=0) are cumulative as of as_of_date "
            "(defaults to today). P&L / Trading accounts (closeIn=1/2) require "
            "date_from/date_to since they only mean something over a period."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "acc_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "One or more account ids from get_chart_of_accounts.",
                },
                "as_of_date": {"type": "string", "description": "YYYY-MM-DD. Only used for Balance Sheet accounts."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD. Only used for P&L/Trading accounts."},
                "date_to": {"type": "string", "description": "YYYY-MM-DD. Only used for P&L/Trading accounts."},
            },
            "required": ["acc_ids"],
        },
    },
]

TOOL_FUNCTIONS = {
    "get_chart_of_accounts": get_chart_of_accounts,
    "get_account_transactions": get_account_transactions,
    "get_account_balance": get_account_balance,
}
