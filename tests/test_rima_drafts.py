"""Governed record-a-transaction / create-an-account tools (drafts.py)."""

import json
from datetime import date, datetime

import pytest

import drafts
from drafts import ToolContext
from models import Accounts, RimaAttachment, TransactionsDetail, TransactionsMaster


def ctx(req="r1", conv="c1", question="", today=date(2026, 9, 21)):
    return ToolContext(conversation_id=conv, request_id=req, question=question, today=today)


# ---------------------------------------------------------------- transaction

class TestTransactionFlow:
    def test_asks_debit_first_with_suggestions(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(question="دفعت إيجار المحل"), search_terms=["إيجار"])
        assert r["next_step"] == "debit_account"
        assert r["status"] == "collecting"
        assert r["suggestions"][0]["name"] == "إيجارات"
        assert r["suggestions"][0]["reason"] == "request"
        assert all(s["name"] not in ("الموجودات", "المصاريف") for s in r["suggestions"])  # never a master

    def test_then_credit_with_history_paired_suggestions(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"))
        r = drafts.update_transaction_draft(coded_db, ctx("r2"), debit_account_id=7)
        assert r["next_step"] == "credit_account"
        # rent has always been paid from the cash box (id 4), so it is offered first
        assert r["suggestions"][0]["id"] == 4
        assert r["suggestions"][0]["reason"] == "history:paired"
        assert 7 not in [s["id"] for s in r["suggestions"]]

    def test_then_amount_then_confirmation(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        r = drafts.update_transaction_draft(coded_db, ctx("r2"), credit_account_id=4)
        assert r["next_step"] == "amount"
        r = drafts.update_transaction_draft(coded_db, ctx("r3"), amount=250.5)
        assert r["next_step"] == "confirmation"
        assert r["status"] == "awaiting_confirmation"
        assert r["draft"]["date"] == "2026-09-21" and r["draft"]["date_source"] == "today"

    def test_credit_given_first_is_kept_but_debit_is_still_asked_first(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), credit_account_id=4, amount=10)
        assert r["next_step"] == "debit_account"
        assert r["draft"]["credit_account"]["id"] == 4

    def test_everything_in_one_message_goes_straight_to_confirmation(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=7, credit_account_id=4, amount=100)
        assert r["next_step"] == "confirmation"

    @pytest.mark.parametrize("bad", [0, -5, "abc", float("nan"), float("inf"), 10**13, True])
    def test_bad_amounts_are_rejected_and_not_stored(self, coded_db, bad):
        r = drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=7, credit_account_id=4, amount=bad)
        assert r["errors"][0]["code"] == "invalid_amount"
        assert r["next_step"] == "amount"

    def test_unknown_account_rejected(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=999)
        assert r["errors"][0]["code"] == "not_found"
        assert r["next_step"] == "debit_account"

    def test_master_account_rejected_with_its_children_offered(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=6)
        e = r["errors"][0]
        assert e["code"] == "master_account"
        assert {c["id"] for c in e["children"]} == {7, 8}
        assert r["next_step"] == "debit_account"

    def test_same_account_on_both_sides_rejected(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=4)
        r = drafts.update_transaction_draft(coded_db, ctx("r2"), credit_account_id=4)
        assert r["errors"][0]["code"] == "same_account"
        assert r["next_step"] == "credit_account"

    @pytest.mark.parametrize("bad", ["yesterday", "2026-13-40", "1999-01-01", "2030-01-01"])
    def test_bad_dates_rejected(self, coded_db, bad):
        r = drafts.update_transaction_draft(coded_db, ctx(), date=bad)
        assert r["errors"][0]["field"] == "date"
        assert r["draft"]["date_source"] == "today"

    def test_user_date_is_used(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), date="2026-09-01")
        assert r["draft"]["date"] == "2026-09-01" and r["draft"]["date_source"] == "user"

    def test_debit_suggestions_fall_back_to_most_used_when_nothing_matches(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(question="xyz"))
        assert r["suggestions"], "should always offer something"
        assert r["suggestions"][0]["reason"] == "history:frequent"
        assert r["suggestions"][0]["id"] == 7  # most-debited account

    def test_arabic_definite_article_and_spelling_variants_match(self, coded_db):
        r = drafts.update_transaction_draft(coded_db, ctx(), search_terms=["الايجار"])  # no hamza, with al-
        assert r["suggestions"][0]["name"] == "إيجارات"


class TestConfirmationGate:
    def _complete(self, db, req="r1"):
        return drafts.update_transaction_draft(db, ctx(req), debit_account_id=7, credit_account_id=4, amount=100)

    def test_cannot_commit_in_the_same_request_that_completed_the_draft(self, coded_db):
        self._complete(coded_db, "r1")
        r = drafts.commit_transaction(coded_db, ctx("r1"))
        assert r["ok"] is False and r["error"] == "needs_user_confirmation"
        assert coded_db.query(TransactionsMaster).count() == 4  # nothing new

    def test_commit_in_a_later_request_saves_a_balanced_entry_and_clears_the_draft(self, coded_db):
        self._complete(coded_db, "r1")
        r = drafts.commit_transaction(coded_db, ctx("r2"))
        assert r["ok"] is True
        m = coded_db.get(TransactionsMaster, r["transaction_id"])
        assert m.date == datetime(2026, 9, 21)
        lines = sorted((d.acc_id, d.debit, d.credit) for d in m.rsTransactionsMaster)
        assert lines == [(4, 0, 100.0), (7, 100.0, 0)]
        assert drafts.get_draft(coded_db, "c1", "transaction") is None

    def test_incomplete_draft_cannot_be_committed(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        r = drafts.commit_transaction(coded_db, ctx("r2"))
        assert r["ok"] is False and r["error"] == "incomplete" and r["next_step"] == "credit_account"

    def test_no_draft(self, coded_db):
        assert drafts.commit_transaction(coded_db, ctx())["error"] == "no_draft"

    def test_changing_a_field_reopens_confirmation_for_the_current_request(self, coded_db):
        self._complete(coded_db, "r1")
        drafts.update_transaction_draft(coded_db, ctx("r2"), amount=200)  # the user changed their mind
        assert drafts.commit_transaction(coded_db, ctx("r2"))["error"] == "needs_user_confirmation"
        assert drafts.commit_transaction(coded_db, ctx("r3"))["ok"] is True

    def test_re_reading_the_state_later_does_not_reopen_confirmation(self, coded_db):
        self._complete(coded_db, "r1")
        drafts.update_transaction_draft(coded_db, ctx("r2"))  # no changes
        assert drafts.commit_transaction(coded_db, ctx("r2"))["ok"] is True

    def test_conversations_are_isolated(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1", conv="A"), debit_account_id=7, credit_account_id=4, amount=1)
        assert drafts.commit_transaction(coded_db, ctx("r2", conv="B"))["error"] == "no_draft"

    def test_accounts_that_became_invalid_are_refused_at_commit(self, coded_db):
        self._complete(coded_db, "r1")
        coded_db.add(Accounts(id=50, code="0020101", name="طفل", closeIn=1, parentAccount=7))  # 7 turns into a header
        coded_db.commit()
        r = drafts.commit_transaction(coded_db, ctx("r2"))
        assert r["ok"] is False and r["errors"][0]["code"] == "master_account"

    def test_cancel_removes_the_draft(self, coded_db):
        self._complete(coded_db, "r1")
        assert drafts.cancel_transaction_draft(coded_db, ctx("r2"))["cancelled"] is True
        assert drafts.get_draft(coded_db, "c1", "transaction") is None
        assert drafts.cancel_transaction_draft(coded_db, ctx("r3"))["cancelled"] is False

    def test_a_draft_is_stored_in_the_db_and_survives_a_new_call(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        coded_db.expire_all()
        r = drafts.update_transaction_draft(coded_db, ctx("r9"))
        assert r["draft"]["debit_account"]["id"] == 7


# -------------------------------------------------------------------- account

class TestAccountCodes:
    def test_next_code_follows_the_hierarchical_scheme(self, coded_db):
        get = lambda i: coded_db.get(Accounts, i)
        assert drafts.next_child_code(coded_db, get(1)) == "00103"    # children 00101, 00102
        assert drafts.next_child_code(coded_db, get(3)) == "0010203"  # children 0010201, 0010202
        assert drafts.next_child_code(coded_db, get(6)) == "00203"    # children 00201, 00202
        assert drafts.next_child_code(coded_db, get(2)) == "0010101"  # no children yet: parent + 01

    def test_parent_without_a_code_has_no_default(self, coded_db):
        coded_db.add(Accounts(id=60, code=None, name="بلا رمز", closeIn=0, parentAccount=None))
        coded_db.commit()
        assert drafts.next_child_code(coded_db, coded_db.get(Accounts, 60)) is None

    def test_overflow_reuses_the_lowest_gap_and_full_returns_none(self, coded_db):
        parent = coded_db.get(Accounts, 11)  # 004
        for n in [i for i in range(1, 100) if i != 7]:
            coded_db.add(Accounts(code=f"004{n:02d}", name=f"c{n}", closeIn=0, parentAccount=11))
        coded_db.commit()
        assert drafts.next_child_code(coded_db, parent) == "00407"  # the only gap
        coded_db.add(Accounts(code="00407", name="c7", closeIn=0, parentAccount=11))
        coded_db.commit()
        assert drafts.next_child_code(coded_db, parent) is None


class TestAccountFlow:
    def test_required_fields_are_asked_in_order(self, coded_db):
        r = drafts.update_account_draft(coded_db, ctx("r1"))
        assert r["next_step"] == "name"
        r = drafts.update_account_draft(coded_db, ctx("r2"), name="محروقات", search_terms=["مصاريف"])
        assert r["next_step"] == "parent_account"
        assert r["suggestions"][0]["name"] == "المصاريف"
        r = drafts.update_account_draft(coded_db, ctx("r3"), parent_account_id=6)
        assert r["next_step"] == "close_in"
        assert r["suggested_close_in"]["value"] == 1  # parent's setting is only a suggestion
        r = drafts.update_account_draft(coded_db, ctx("r4"), close_in=1)
        assert r["next_step"] == "code"
        assert r["suggested_code"] == "00203"
        r = drafts.update_account_draft(coded_db, ctx("r5"), code="00203")
        assert r["next_step"] == "confirmation" and r["status"] == "awaiting_confirmation"

    def test_parent_is_required_no_top_level_accounts(self, coded_db):
        r = drafts.update_account_draft(coded_db, ctx(), name="جذر", close_in=0)
        assert r["next_step"] == "parent_account"
        assert drafts.commit_account(coded_db, ctx("r2"))["error"] == "incomplete"

    def test_parent_with_postings_and_no_children_is_refused(self, coded_db):
        # 00201 (rent) is a detail account with postings: it can't become a header
        r = drafts.update_account_draft(coded_db, ctx(), name="x", parent_account_id=7)
        assert r["errors"][0]["code"] == "parent_has_postings"
        assert r["next_step"] == "parent_account"

    def test_an_unposted_detail_account_may_become_a_parent(self, coded_db):
        r = drafts.update_account_draft(coded_db, ctx(), name="x", parent_account_id=2)  # 00101, no postings
        assert not r["errors"] and r["next_step"] == "close_in"

    def test_master_with_postings_is_still_fine(self, coded_db):
        coded_db.add(TransactionsDetail(idMaster=1, acc_id=6, debit=1, credit=0, description="stray"))
        coded_db.commit()
        r = drafts.update_account_draft(coded_db, ctx(), name="x", parent_account_id=6)
        assert not r["errors"]

    @pytest.mark.parametrize("code,expected", [
        ("0020", "code_scheme"),     # wrong width
        ("00301", "code_scheme"),    # wrong prefix
        ("002AB", "invalid_code"),
        ("00200", "code_scheme"),    # suffix 00 is not allowed
        ("00201", "code_taken"),
    ])
    def test_bad_codes_rejected(self, coded_db, code, expected):
        r = drafts.update_account_draft(coded_db, ctx(), name="x", parent_account_id=6, close_in=1, code=code)
        assert r["errors"][0]["code"] == expected
        assert r["next_step"] == "code"

    def test_duplicate_sibling_name_rejected(self, coded_db):
        r = drafts.update_account_draft(coded_db, ctx(), name="رواتب", parent_account_id=6)
        assert r["errors"][0]["code"] == "duplicate_name"
        assert r["next_step"] == "name"

    def test_same_name_under_a_different_parent_is_fine(self, coded_db):
        r = drafts.update_account_draft(coded_db, ctx(), name="رواتب", parent_account_id=9)
        assert not r["errors"]

    def test_close_in_accepts_labels(self, coded_db):
        for label, value in [("Balance Sheet", 0), ("P&L", 1), ("Trading", 2), ("الميزانية العمومية", 0)]:
            r = drafts.update_account_draft(coded_db, ctx(), close_in=label)
            assert r["draft"]["close_in"] == value, label

    def test_changing_the_parent_drops_the_now_wrong_code(self, coded_db):
        drafts.update_account_draft(coded_db, ctx("r1"), name="x", parent_account_id=6, close_in=1, code="00203")
        r = drafts.update_account_draft(coded_db, ctx("r2"), parent_account_id=9)
        assert r["draft"]["code"] is None and r["next_step"] == "code" and r["suggested_code"] == "00302"

    def test_create_requires_confirmation_in_a_later_request(self, coded_db):
        drafts.update_account_draft(coded_db, ctx("r1"), name="محروقات", parent_account_id=6, close_in=1, code="00203")
        assert drafts.commit_account(coded_db, ctx("r1"))["error"] == "needs_user_confirmation"
        assert coded_db.query(Accounts).filter(Accounts.name == "محروقات").count() == 0
        r = drafts.commit_account(coded_db, ctx("r2"))
        assert r["ok"] is True
        acc = coded_db.get(Accounts, r["account"]["id"])
        assert (acc.code, acc.name, acc.closeIn, acc.parentAccount) == ("00203", "محروقات", 1, 6)
        assert drafts.get_draft(coded_db, "c1", "account") is None

    def test_the_new_account_is_a_detail_account(self, coded_db):
        from tools import _is_master, _load_accounts
        drafts.update_account_draft(coded_db, ctx("r1"), name="محروقات", parent_account_id=6, close_in=1, code="00203")
        new_id = drafts.commit_account(coded_db, ctx("r2"))["account"]["id"]
        _, children = _load_accounts(coded_db)
        assert not _is_master(new_id, children)
        assert coded_db.query(TransactionsDetail).filter(TransactionsDetail.acc_id == new_id).count() == 0

    def test_full_parent_is_reported_and_skipped(self, coded_db):
        for n in range(1, 100):
            coded_db.add(Accounts(code=f"004{n:02d}", name=f"c{n}", closeIn=0, parentAccount=11))
        coded_db.commit()
        r = drafts.update_account_draft(coded_db, ctx(), name="x", parent_account_id=11)
        assert r["errors"][0]["code"] == "parent_full"
        assert r["next_step"] == "parent_account"


class TestAccountInsideATransaction:
    def test_new_account_fills_the_slot_and_the_transaction_resumes(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), credit_account_id=4, amount=80)
        drafts.update_account_draft(
            coded_db, ctx("r2"), name="محروقات", parent_account_id=6, close_in=1, code="00203", for_slot="debit"
        )
        r = drafts.commit_account(coded_db, ctx("r3"))
        assert r["ok"] and r["transaction_draft"]["transaction_next_step"] == "confirmation"
        tx = drafts.get_draft(coded_db, "c1", "transaction")
        assert tx.status == "awaiting_confirmation"
        # the transaction still needs its OWN later confirmation
        assert drafts.commit_transaction(coded_db, ctx("r3"))["error"] == "needs_user_confirmation"
        done = drafts.commit_transaction(coded_db, ctx("r4"))
        assert done["ok"] and done["debit_account"]["name"] == "محروقات"

    def test_slot_fill_with_missing_fields_keeps_collecting(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"))
        drafts.update_account_draft(coded_db, ctx("r2"), name="x", parent_account_id=6, close_in=1, code="00203", for_slot="debit")
        r = drafts.commit_account(coded_db, ctx("r3"))
        assert r["transaction_draft"]["transaction_next_step"] == "credit_account"


# ------------------------------------------------------ document + pending list

FACTS = {"vendor": "شركة الكهرباء", "document_type": "invoice", "date": "2026-08-30", "total": 1250.0, "currency": "JOD",
         "items": [{"description": "فاتورة كهرباء", "amount": 1250.0}], "legible": True}


@pytest.fixture()
def with_doc(coded_db):
    coded_db.add(Accounts(id=70, code="00203", name="كهرباء ومياه", closeIn=1, parentAccount=6))
    coded_db.add(RimaAttachment(id=1, conversation_id="c1", mime="image/jpeg", filename="bill.jpg",
                                data=b"\xff\xd8\xff\xe0FAKE", facts=json.dumps(FACTS, ensure_ascii=False)))
    coded_db.commit()
    return coded_db


class TestDocument:
    def test_document_facts_drive_the_first_suggestions_and_date(self, with_doc):
        r = drafts.update_transaction_draft(with_doc, ctx(question="سجل هالفاتورة"))
        assert r["suggestions"][0]["name"] == "كهرباء ومياه"
        assert r["suggestions"][0]["reason"] == "document"
        assert r["draft"]["date"] == "2026-08-30" and r["draft"]["date_source"] == "document"
        assert r["draft"]["document_attached"] is True

    def test_document_outranks_the_users_words(self, with_doc):
        r = drafts.update_transaction_draft(with_doc, ctx(), search_terms=["إيجار"])
        assert r["suggestions"][0]["reason"] == "document"
        assert "إيجارات" in [s["name"] for s in r["suggestions"]]  # the user's words still show up, second

    def test_the_document_total_is_only_a_proposal_the_user_must_confirm(self, with_doc):
        drafts.update_transaction_draft(with_doc, ctx("r1"), debit_account_id=70)
        r = drafts.update_transaction_draft(with_doc, ctx("r2"), credit_account_id=4)
        assert r["next_step"] == "amount"
        assert r["suggested_amount"]["value"] == 1250.0
        assert r["draft"]["amount"] is None

    def test_a_differing_amount_is_flagged(self, with_doc):
        r = drafts.update_transaction_draft(with_doc, ctx(), debit_account_id=70, credit_account_id=4, amount=1000)
        assert "differs" in r["notes"][0]

    def test_the_document_is_saved_with_the_entry_byte_for_byte(self, with_doc):
        drafts.update_transaction_draft(with_doc, ctx("r1"), debit_account_id=70, credit_account_id=4, amount=1250)
        done = drafts.commit_transaction(with_doc, ctx("r2"))
        assert done["document_saved"] is True
        m = with_doc.get(TransactionsMaster, done["transaction_id"])
        assert m.document == b"\xff\xd8\xff\xe0FAKE" and m.document_mime == "image/jpeg" and m.document_name == "bill.jpg"
        assert m.date == datetime(2026, 8, 30)
        assert with_doc.query(RimaAttachment).count() == 0  # the temporary row is gone

    def test_cancel_discards_the_document(self, with_doc):
        drafts.update_transaction_draft(with_doc, ctx("r1"), debit_account_id=70)
        drafts.cancel_transaction_draft(with_doc, ctx("r2"))
        assert with_doc.query(RimaAttachment).count() == 0

    def test_listing_transactions_does_not_load_the_image(self, with_doc):
        drafts.update_transaction_draft(with_doc, ctx("r1"), debit_account_id=70, credit_account_id=4, amount=1)
        drafts.commit_transaction(with_doc, ctx("r2"))
        with_doc.expire_all()
        m = with_doc.query(TransactionsMaster).filter(TransactionsMaster.document_mime.isnot(None)).one()
        assert "document" not in m.__dict__  # deferred: not loaded until touched


class TestPending:
    def test_lists_and_describes_open_drafts(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        drafts.update_account_draft(coded_db, ctx("r2"), name="x")
        pending = drafts.list_pending_drafts(coded_db, "c1")
        assert [(d["kind"], d["next_step"]) for d in pending] == [("transaction", "credit_account"), ("account", "parent_account")]
        assert drafts.list_pending_drafts(coded_db, "other") == []

    def test_prompt_block_carries_the_reminder_rule(self, coded_db):
        assert drafts.pending_drafts_prompt(coded_db, "c1") == ""
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        block = drafts.pending_drafts_prompt(coded_db, "c1")
        assert "credit_account" in block and "غير محفوظة" in block

    def test_button_confirm_needs_a_complete_read_back_draft(self, coded_db):
        drafts.update_transaction_draft(coded_db, ctx("r1"), debit_account_id=7)
        assert drafts.confirm_draft(coded_db, "c1", "transaction")["error"] == "incomplete"
        drafts.update_transaction_draft(coded_db, ctx("r2"), credit_account_id=4, amount=5)
        r = drafts.confirm_draft(coded_db, "c1", "transaction", today=date(2026, 9, 21))
        assert r["ok"] is True  # a real button press needs no later request

    def test_button_confirm_and_cancel_for_accounts(self, coded_db):
        drafts.update_account_draft(coded_db, ctx("r1"), name="محروقات", parent_account_id=6, close_in=1, code="00203")
        assert drafts.confirm_draft(coded_db, "c1", "account")["ok"] is True
        drafts.update_account_draft(coded_db, ctx("r2"), name="آخر")
        assert drafts.cancel_draft(coded_db, "c1", "account")["cancelled"] is True
