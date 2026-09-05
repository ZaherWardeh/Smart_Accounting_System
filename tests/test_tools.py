from models import TransactionsDetail
from tools import _parse_date, get_account_balance, get_account_transactions, get_chart_of_accounts


def test_chart_of_accounts_master_vs_book(seeded_db):
    chart = {a["id"]: a for a in get_chart_of_accounts(seeded_db)}

    assert chart[1]["account_type"] == "master"
    assert chart[5]["account_type"] == "master"
    assert chart[2]["account_type"] == "book"
    assert chart[6]["account_type"] == "book"
    assert chart[7]["account_type"] == "book"
    assert chart[1]["closeIn"] == "Balance Sheet"
    assert chart[5]["closeIn"] == "P&L"


def test_account_transactions_master_rolls_up_descendants(seeded_db):
    txns = get_account_transactions(seeded_db, acc_id=1)

    assert len(txns) == 3
    assert {t["acc_id"] for t in txns} == {2, 3}


def test_account_transactions_book_account_only(seeded_db):
    txns = get_account_transactions(seeded_db, acc_id=2)

    assert len(txns) == 2
    assert all(t["acc_id"] == 2 for t in txns)


def test_account_transactions_date_range_excludes_outside(seeded_db):
    txns = get_account_transactions(seeded_db, acc_id=1, date_from="2026-02-01")

    assert len(txns) == 2
    assert all(t["date"] >= "2026-02-01" for t in txns)


def test_account_transactions_unknown_account_returns_empty(seeded_db):
    assert get_account_transactions(seeded_db, acc_id=999) == []


def test_balance_sheet_book_account_as_of_date(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[2], as_of_date="2026-01-31")

    assert result["debit_sum"] == 1000
    assert result["credit_sum"] == 0
    assert result["net"] == 1000


def test_balance_sheet_master_account_rolls_up_and_respects_as_of_date(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[1], as_of_date="2026-02-28")

    assert result["debit_sum"] == 1500
    assert result["credit_sum"] == 0
    breakdown = result["breakdown"][0]
    assert breakdown["account_type"] == "master"
    # includes the master's own id defensively, in case something was ever
    # posted directly to it, plus its descendant book accounts.
    assert {a["id"] for a in breakdown["resolved_book_accounts"]} == {1, 2, 3}


def test_balance_sheet_default_as_of_is_cumulative_to_now(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[2])

    assert result["debit_sum"] == 1000
    assert result["credit_sum"] == 200
    assert result["net"] == 800


def test_pnl_master_account_requires_period(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[5], date_from="2026-01-01", date_to="2026-03-31")

    assert result["credit_sum"] == 1500
    assert result["debit_sum"] == 0


def test_pnl_book_account_period_edge(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[7], date_from="2026-01-01", date_to="2026-03-01")

    assert result["debit_sum"] == 200

    result_before = get_account_balance(seeded_db, acc_ids=[7], date_from="2026-01-01", date_to="2026-02-28")
    assert result_before["debit_sum"] == 0


def test_cross_account_aggregation_returns_combined_and_breakdown(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[2, 3])

    assert result["debit_sum"] == 1500
    assert result["credit_sum"] == 200
    assert len(result["breakdown"]) == 2


def test_balance_unknown_account_reports_error_in_breakdown(seeded_db):
    result = get_account_balance(seeded_db, acc_ids=[999])

    assert result["breakdown"][0]["error"] == "Account not found"


def test_postings_made_directly_on_a_master_account_are_not_dropped(seeded_db):
    # nothing should post directly to a header account in practice, but
    # nothing in the schema prevents it either - it must still be counted.
    seeded_db.add(
        TransactionsDetail(idMaster=1, acc_id=1, debit=999, credit=0, description="posted straight to Assets")
    )
    seeded_db.commit()

    result = get_account_balance(seeded_db, acc_ids=[1], as_of_date="2026-12-31")
    assert result["debit_sum"] == 1000 + 500 + 999
    assert result["credit_sum"] == 200

    txns = get_account_transactions(seeded_db, acc_id=1, date_from="2026-01-01", date_to="2026-12-31")
    assert any(t["acc_id"] == 1 for t in txns)


def test_parse_date_bare_date_is_bumped_to_end_of_day():
    dt = _parse_date("2026-01-31", end_of_day=True)

    assert (dt.hour, dt.minute, dt.second) == (23, 59, 59)


def test_parse_date_explicit_midnight_timestamp_is_left_alone():
    dt = _parse_date("2026-01-31T00:00:00", end_of_day=True)

    assert (dt.hour, dt.minute, dt.second) == (0, 0, 0)
