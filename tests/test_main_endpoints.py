import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture()
def client(seeded_db):
    def override_get_db():
        yield seeded_db

    main.app.dependency_overrides[main.get_db] = override_get_db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


def test_html_pages_serve_ok(client):
    for path in ("/", "/accounts", "/transactions", "/reports", "/chat"):
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]


def test_static_assets_serve_ok(client):
    res = client.get("/static/app.css")
    assert res.status_code == 200


def test_chart_of_accounts_endpoint(client):
    res = client.get("/reports/chart-of-accounts")
    assert res.status_code == 200
    data = res.json()
    assert {a["id"] for a in data} == {1, 2, 3, 4, 5, 6, 7}
    assert next(a for a in data if a["id"] == 1)["account_type"] == "master"
    assert next(a for a in data if a["id"] == 2)["account_type"] == "book"


def test_statement_endpoint(client):
    res = client.get("/reports/statement/1", params={"date_from": "2026-02-01"})
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 2  # Bank sale + Paid expense, both after 2026-02-01


def test_statement_endpoint_unknown_account_404(client):
    res = client.get("/reports/statement/9999")
    assert res.status_code == 404


def test_balance_endpoint(client):
    res = client.get("/reports/balance", params={"acc_ids": [2, 3]})
    assert res.status_code == 200
    data = res.json()
    assert data["debit_sum"] == 1500
    assert data["credit_sum"] == 200


def test_delete_account_blocked_by_children(client):
    res = client.delete("/accounts/1")  # Assets, has children 2 and 3
    assert res.status_code == 409


def test_delete_account_blocked_by_transactions(client):
    res = client.delete("/accounts/2")  # Cash, has transactions posted to it
    assert res.status_code == 409


def test_delete_account_succeeds_when_unused(client):
    created = client.post("/accounts/", json={"name": "Unused", "closeIn": 0, "parentAccount": None})
    assert created.status_code == 201
    new_id = created.json()["id"]

    deleted = client.delete(f"/accounts/{new_id}")
    assert deleted.status_code == 204
    assert client.get(f"/accounts/{new_id}").status_code == 404


def test_delete_account_unknown_id_404(client):
    assert client.delete("/accounts/9999").status_code == 404


def test_delete_transaction_removes_it_and_its_details(client):
    res = client.delete("/transactions/1")
    assert res.status_code == 204
    assert client.get("/transactions/1").status_code == 404
    # cascade should have removed the detail rows too, not just the master
    remaining_cash_statement = client.get("/reports/statement/2").json()
    assert all(row["transaction_id"] != 1 for row in remaining_cash_statement)


def test_delete_transaction_unknown_id_404(client):
    assert client.delete("/transactions/9999").status_code == 404


def test_transactions_expose_line_descriptions(client):
    # the mobile app edits entries from this payload; a missing description would be lost on save
    one = client.get("/transactions/1").json()
    assert sorted(d["description"] for d in one["details"]) == ["cash in", "sale"]
    listed = {t["id"]: t for t in client.get("/transactions/").json()}
    assert sorted(d["description"] for d in listed[2]["details"]) == ["bank in", "sale"]


def test_create_transaction_accepts_decimal_amounts_that_sum_equal(client):
    # 0.1 + 0.2 != 0.3 in floating point, but this is a balanced entry
    body = {
        "date": "2026-04-01T00:00:00",
        "notes": "decimals",
        "items": [
            {"acc_id": 2, "debit": 0.1, "credit": 0, "description": "a"},
            {"acc_id": 3, "debit": 0.2, "credit": 0, "description": "b"},
            {"acc_id": 6, "debit": 0, "credit": 0.3, "description": "c"},
        ],
    }
    res = client.post("/transactions/", json=body)
    assert res.status_code == 201, res.text


def test_create_transaction_still_rejects_unbalanced(client):
    body = {
        "items": [
            {"acc_id": 2, "debit": 10.00, "credit": 0, "description": "a"},
            {"acc_id": 6, "debit": 0, "credit": 10.01, "description": "b"},
        ],
    }
    assert client.post("/transactions/", json=body).status_code == 406


def test_serve_web_off_runs_api_only(monkeypatch, seeded_db):
    import importlib

    monkeypatch.setenv("SERVE_WEB", "0")
    api_only = importlib.reload(main)
    try:
        def override_get_db():
            yield seeded_db

        api_only.app.dependency_overrides[api_only.get_db] = override_get_db
        c = TestClient(api_only.app)
        for page in ("/", "/chat", "/static/app.css"):
            assert c.get(page).status_code == 404, page
        # /accounts etc. only redirect to the JSON API (trailing slash) - no HTML page anywhere
        for page in ("/accounts", "/transactions", "/reports", "/chat"):
            assert "text/html" not in c.get(page).headers.get("content-type", ""), page
        # the API itself is untouched
        assert c.get("/health").status_code == 200
        assert c.get("/accounts/").status_code == 200
        assert c.get("/transactions/1").status_code == 200
    finally:
        monkeypatch.delenv("SERVE_WEB")
        importlib.reload(main)
