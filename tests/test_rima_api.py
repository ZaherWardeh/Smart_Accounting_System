"""HTTP layer for Rima's drafts and documents, attachment validation, and the
column migration for databases created before documents existed."""

import base64
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import database
import documents
import drafts
import graph
import main
from drafts import ToolContext
from fakes import FakeFunctionCall, FakePart, FakeResponse, install_fake_client
from models import Accounts, RimaAttachment, RimaDraft, TransactionsMaster

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"0" * 64


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture()
def client(coded_db):
    def override_get_db():
        yield coded_db

    main.app.dependency_overrides[main.get_db] = override_get_db
    graph.clear_conversation("api")
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    graph.clear_conversation("api")


def ctx(req="r1", conv="api"):
    return ToolContext(conversation_id=conv, request_id=req, question="")


def scripted(*replies):
    queue = list(replies)

    def fn(model, contents, config=None):
        if getattr(config, "response_mime_type", None) == "application/json":
            return FakeResponse(parts=[FakePart()], text=json.dumps({"legible": True, "items": [], "vendor": "X", "total": 5}))
        return queue.pop(0)

    return fn


def call(tool, /, **args):
    return FakeResponse(parts=[FakePart(function_call=FakeFunctionCall(name=tool, args=args))])


def say(text):
    return FakeResponse(parts=[FakePart()], text=text)


# ------------------------------------------------------------- attachments (unit)

class TestDecodeAttachment:
    @pytest.mark.parametrize("data,mime", [(JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp")])
    def test_accepts_real_images_by_their_bytes(self, data, mime):
        assert documents.decode_attachment(b64(data)) == (mime, data)

    def test_declared_type_is_never_trusted(self):
        assert documents.decode_attachment(b64(PNG), "image/jpeg")[0] == "image/png"

    def test_data_url_prefix_is_accepted(self):
        assert documents.decode_attachment("data:image/jpeg;base64," + b64(JPEG))[1] == JPEG

    @pytest.mark.parametrize("bad", ["", "not base64!!", b64(b"just some text, not an image"), b64(b"%PDF-1.4 ...")],
                             ids=["empty", "bad_base64", "text", "pdf"])
    def test_rejects_non_images(self, bad):
        with pytest.raises(documents.AttachmentError):
            documents.decode_attachment(bad)

    def test_rejects_oversized_images(self):
        big = JPEG + b"0" * (documents.MAX_BYTES + 1)
        with pytest.raises(documents.AttachmentError, match="too large"):
            documents.decode_attachment(b64(big))


class TestNormalizeFacts:
    def test_junk_is_coerced_to_the_fixed_shape(self):
        f = documents.normalize_facts({
            "legible": 1, "vendor": "  A   B  ", "date": "31/12/2026", "total": "1,250.456", "tax": "abc",
            "items": [{"description": "x", "amount": "5"}, {"description": ""}, "junk"] + [{"description": "i"}] * 60,
        })
        assert f["vendor"] == "A B" and f["date"] is None and f["total"] == 1250.46 and f["tax"] is None
        assert f["legible"] is True and 0 < len(f["items"]) <= documents.MAX_ITEMS  # capped, junk entries dropped
        assert documents.normalize_facts("nonsense") == {"legible": False, "items": []}

    def test_absurd_dates_are_dropped(self):
        assert documents.normalize_facts({"date": "1850-01-01"})["date"] is None


# ------------------------------------------------------------------ /ask_ai

class TestAskAI:
    def test_reply_lists_the_open_drafts(self, client, monkeypatch):
        install_fake_client(monkeypatch, scripted(call("update_transaction_draft", debit_account_id=7), say("والدائن؟")))
        r = client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "سجل قيد إيجار"})
        assert r.status_code == 200
        body = r.json()
        assert body["answer"] == "والدائن؟"
        (d,) = body["pending_drafts"]
        assert d["kind"] == "transaction" and d["next_step"] == "credit_account" and d["status"] == "collecting"
        assert d["draft"]["debit_account"]["id"] == 7

    def test_no_drafts_gives_an_empty_list(self, client, monkeypatch):
        install_fake_client(monkeypatch, scripted(say("أهلاً")))
        body = client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "مرحبا"}).json()
        assert body["pending_drafts"] == []

    def test_image_only_message_is_accepted_and_stored(self, client, monkeypatch, coded_db):
        install_fake_client(monkeypatch, scripted(say("قرأت المستند")))
        r = client.post("/reports/ask_ai", json={"conversation_id": "api", "attachment": {"data_base64": b64(JPEG), "filename": "a.jpg"}})
        assert r.status_code == 200, r.text
        att = coded_db.query(RimaAttachment).one()
        assert att.mime == "image/jpeg" and att.filename == "a.jpg"

    def test_nothing_to_send_is_a_validation_error(self, client):
        assert client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "  "}).status_code == 422

    def test_old_clients_without_attachment_still_work(self, client, monkeypatch):
        install_fake_client(monkeypatch, scripted(say("ok")))
        assert client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "hi"}).status_code == 200

    @pytest.mark.parametrize("kind,status", [("not_base64", 400), ("text_file", 400), ("too_big", 413)])
    def test_bad_attachments_are_rejected_before_any_llm_call(self, client, monkeypatch, kind, status):
        payload = {
            "not_base64": "not base64!!",
            "text_file": b64(b"plain text file"),
            "too_big": b64(JPEG + b"0" * (documents.MAX_BYTES + 10)),
        }[kind]
        install_fake_client(monkeypatch, lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM must not be called")))
        r = client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "x", "attachment": {"data_base64": payload}})
        assert r.status_code == status


# ------------------------------------------------------------------ /drafts

class TestDraftRoutes:
    def test_list_confirm_transaction(self, client, coded_db):
        drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=7, credit_account_id=4, amount=42)
        listed = client.get("/drafts/api").json()
        assert [d["kind"] for d in listed] == ["transaction"] and listed[0]["ready_to_confirm"] is True

        r = client.post("/drafts/api/transaction/confirm")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert r.json()["pending_drafts"] == []
        assert coded_db.query(TransactionsMaster).count() == 5

    def test_confirm_is_refused_while_incomplete(self, client, coded_db):
        drafts.update_transaction_draft(coded_db, ctx(), debit_account_id=7)
        r = client.post("/drafts/api/transaction/confirm")
        assert r.status_code == 409 and r.json()["detail"]["next_step"] == "credit_account"
        assert coded_db.query(TransactionsMaster).count() == 4

    def test_confirm_without_a_draft_is_404(self, client):
        assert client.post("/drafts/api/transaction/confirm").status_code == 404

    def test_unknown_kind_is_404(self, client):
        assert client.post("/drafts/api/refund/confirm").status_code == 404
        assert client.post("/drafts/api/refund/cancel").status_code == 404

    def test_cancel(self, client, coded_db):
        drafts.update_account_draft(coded_db, ctx(), name="x")
        r = client.post("/drafts/api/account/cancel")
        assert r.status_code == 200 and r.json()["cancelled"] is True and r.json()["pending_drafts"] == []
        assert coded_db.query(RimaDraft).count() == 0

    def test_confirm_account_creates_it(self, client, coded_db):
        drafts.update_account_draft(coded_db, ctx(), name="محروقات", parent_account_id=6, close_in=1, code="00203")
        r = client.post("/drafts/api/account/confirm")
        assert r.status_code == 200 and r.json()["account"]["code"] == "00203"
        assert coded_db.query(Accounts).filter(Accounts.code == "00203").count() == 1

    def test_button_press_is_written_into_the_conversation_memory(self, client, monkeypatch, coded_db):
        install_fake_client(monkeypatch, scripted(
            call("update_transaction_draft", debit_account_id=7, credit_account_id=4, amount=9), say("تأكيد؟")))
        client.post("/reports/ask_ai", json={"conversation_id": "api", "question": "سجل"})
        client.post("/drafts/api/transaction/confirm")
        history = graph._get_history("api")
        assert "pressed Confirm" in str(history[-2].parts[0].text)


# ------------------------------------------------------ documents on entries

class TestDocumentEndpoints:
    def _entry_with_document(self, db):
        db.add(RimaAttachment(id=5, conversation_id="api", mime="image/png", filename="bill.png", data=PNG, facts="{}"))
        db.commit()
        drafts.update_transaction_draft(db, ctx("r1"), debit_account_id=7, credit_account_id=4, amount=5)
        return drafts.commit_transaction(db, ctx("r2"))["transaction_id"]

    def test_document_round_trips_byte_for_byte(self, client, coded_db):
        tid = self._entry_with_document(coded_db)
        r = client.get(f"/transactions/{tid}/document")
        assert r.status_code == 200
        assert r.content == PNG and r.headers["content-type"] == "image/png"
        assert 'filename="bill.png"' in r.headers["content-disposition"]

    def test_lists_flag_documents_without_shipping_the_bytes(self, client, coded_db):
        tid = self._entry_with_document(coded_db)
        rows = {t["id"]: t for t in client.get("/transactions/").json()}
        assert rows[tid]["has_document"] is True and rows[1]["has_document"] is False
        assert "document" not in rows[tid]
        assert client.get(f"/transactions/{tid}").json()["has_document"] is True

    def test_entry_without_a_document_is_404(self, client):
        assert client.get("/transactions/1/document").status_code == 404
        assert client.get("/transactions/9999/document").status_code == 404

    def test_editing_an_entry_keeps_its_document(self, client, coded_db):
        tid = self._entry_with_document(coded_db)
        body = {"id": tid, "date": "2026-09-01T00:00:00", "notes": "edited",
                "items": [{"acc_id": 7, "debit": 5, "credit": 0, "description": "a"},
                          {"acc_id": 4, "debit": 0, "credit": 5, "description": "b"}]}
        assert client.put("/transactions/", json=body).status_code in (200, 201, 202)
        assert client.get(f"/transactions/{tid}/document").content == PNG


# ---------------------------------------------------------------- maintenance

def test_stale_unclaimed_attachments_are_cleaned_but_claimed_ones_are_kept(coded_db):
    old = datetime.utcnow() - timedelta(days=documents.STALE_DAYS + 1)
    coded_db.add_all([
        RimaAttachment(id=1, conversation_id="a", mime="image/png", data=PNG, facts="{}", created_at=old),
        RimaAttachment(id=2, conversation_id="b", mime="image/png", data=PNG, facts="{}", created_at=old),
        RimaAttachment(id=3, conversation_id="c", mime="image/png", data=PNG, facts="{}"),
    ])
    coded_db.commit()
    drafts.update_transaction_draft(coded_db, ToolContext("b", "r", ""), debit_account_id=7)  # claims attachment 2
    assert documents.cleanup_stale_attachments(coded_db) == 1
    assert sorted(a.id for a in coded_db.query(RimaAttachment).all()) == [2, 3]


def test_a_new_upload_replaces_an_unclaimed_one_but_not_a_claimed_one(coded_db):
    documents.save_attachment(coded_db, "x", "image/png", PNG, "1.png", {})
    documents.save_attachment(coded_db, "x", "image/png", PNG, "2.png", {})
    assert [a.filename for a in coded_db.query(RimaAttachment).all()] == ["2.png"]
    drafts.update_transaction_draft(coded_db, ToolContext("x", "r", ""), debit_account_id=7)  # claims 2.png
    documents.save_attachment(coded_db, "x", "image/png", PNG, "3.png", {})
    assert sorted(a.filename for a in coded_db.query(RimaAttachment).all()) == ["2.png", "3.png"]


class TestLegacyDatabaseMigration:
    def _legacy_engine(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
        with engine.begin() as c:
            c.execute(text('CREATE TABLE "TransactionsMaster" (id INTEGER PRIMARY KEY, date DATETIME NOT NULL, notes VARCHAR)'))
            c.execute(text("INSERT INTO \"TransactionsMaster\" (id, date, notes) VALUES (1, '2025-01-01 00:00:00', 'old entry')"))
        return engine

    def test_adds_the_missing_columns_and_keeps_the_data(self, tmp_path):
        engine = self._legacy_engine(tmp_path)
        assert sorted(database.ensure_columns(engine)) == [
            "TransactionsMaster.document", "TransactionsMaster.document_mime", "TransactionsMaster.document_name"]
        cols = {c["name"] for c in inspect(engine).get_columns("TransactionsMaster")}
        assert {"document", "document_mime", "document_name"} <= cols
        with engine.connect() as c:
            row = c.execute(text('SELECT notes, document_mime FROM "TransactionsMaster" WHERE id = 1')).one()
        assert tuple(row) == ("old entry", None)

    def test_is_idempotent(self, tmp_path):
        engine = self._legacy_engine(tmp_path)
        database.ensure_columns(engine)
        assert database.ensure_columns(engine) == []

    def test_fresh_databases_are_untouched(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
        database.Base.metadata.create_all(engine)
        assert database.ensure_columns(engine) == []

    def test_the_orm_can_read_and_write_documents_after_migrating(self, tmp_path):
        from sqlalchemy.orm import sessionmaker
        engine = self._legacy_engine(tmp_path)
        database.ensure_columns(engine)
        database.Base.metadata.create_all(engine)  # creates the new Rima tables next to the old one
        db = sessionmaker(bind=engine)()
        old = db.query(TransactionsMaster).filter(TransactionsMaster.id == 1).one()
        assert old.document_mime is None
        db.add(TransactionsMaster(id=2, date=datetime(2026, 1, 1), notes="new", document=PNG, document_mime="image/png"))
        db.commit()
        assert db.get(TransactionsMaster, 2).document == PNG
