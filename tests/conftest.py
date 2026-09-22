import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Importing `main` builds/migrates the default engine. Point it at a throwaway in-memory
# database BEFORE anything imports it, so running the tests can never touch accounting.db.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Base
from models import Accounts, TransactionsDetail, TransactionsMaster


@pytest.fixture()
def db_session():
    # StaticPool keeps a single shared connection alive for the life of the
    # engine regardless of which thread uses it - required because FastAPI's
    # TestClient runs sync path operations in a worker thread, and plain
    # :memory: SQLite otherwise hands each thread its own empty database.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def seeded_db(db_session):
    """Chart:
    1 Assets     (BS, master)      -> 2 Cash (BS, book), 3 Bank (BS, book)
    4 Liabilities(BS, book, leaf)
    5 Revenue    (P&L, master)     -> 6 Sales (P&L, book)
    7 Expenses   (P&L, book, leaf)

    Transactions:
    T1 2026-01-10  Cash   debit 1000 / Sales  credit 1000  "Cash sale"
    T2 2026-02-15  Bank   debit  500 / Sales  credit  500  "Bank sale"
    T3 2026-03-01  Expenses debit 200 / Cash  credit  200  "Paid expense"
    """
    accounts = [
        Accounts(id=1, name="Assets", closeIn=0, parentAccount=None),
        Accounts(id=2, name="Cash", closeIn=0, parentAccount=1),
        Accounts(id=3, name="Bank", closeIn=0, parentAccount=1),
        Accounts(id=4, name="Liabilities", closeIn=0, parentAccount=None),
        Accounts(id=5, name="Revenue", closeIn=1, parentAccount=None),
        Accounts(id=6, name="Sales", closeIn=1, parentAccount=5),
        Accounts(id=7, name="Expenses", closeIn=1, parentAccount=None),
    ]
    db_session.add_all(accounts)
    db_session.commit()

    def add_txn(txn_id, date_str, notes, lines):
        master = TransactionsMaster(id=txn_id, date=datetime.strptime(date_str, "%Y-%m-%d"), notes=notes)
        db_session.add(master)
        db_session.flush()
        for acc_id, debit, credit, desc in lines:
            db_session.add(
                TransactionsDetail(idMaster=txn_id, acc_id=acc_id, debit=debit, credit=credit, description=desc)
            )
        db_session.commit()

    add_txn(1, "2026-01-10", "Cash sale", [(2, 1000, 0, "cash in"), (6, 0, 1000, "sale")])
    add_txn(2, "2026-02-15", "Bank sale", [(3, 500, 0, "bank in"), (6, 0, 500, "sale")])
    add_txn(3, "2026-03-01", "Paid expense", [(7, 200, 0, "expense"), (2, 0, 200, "cash out")])

    return db_session


@pytest.fixture()
def coded_db(db_session):
    """A chart shaped like the real one: 3-digit roots, +2 digits per level.

    001 الموجودات (BS, master)
      00101 موجودات ثابتة (book)
      00102 موجودات متداولة (master)
        0010201 الصندوق (book)
        0010202 البنك (book)
    002 المصاريف (P&L, master)
      00201 إيجارات (book)
      00202 رواتب (book)
    003 المبيعات (P&L, master)
      00301 مبيعات نقدية (book)
    004 حساب فارغ (BS, book leaf, no postings)
    """
    rows = [
        (1, "001", "الموجودات", 0, None),
        (2, "00101", "موجودات ثابتة", 0, 1),
        (3, "00102", "موجودات متداولة", 0, 1),
        (4, "0010201", "الصندوق", 0, 3),
        (5, "0010202", "البنك", 0, 3),
        (6, "002", "المصاريف", 1, None),
        (7, "00201", "إيجارات", 1, 6),
        (8, "00202", "رواتب", 1, 6),
        (9, "003", "المبيعات", 1, None),
        (10, "00301", "مبيعات نقدية", 1, 9),
        (11, "004", "حساب فارغ", 0, None),
    ]
    db_session.add_all([Accounts(id=i, code=c, name=n, closeIn=ci, parentAccount=p) for i, c, n, ci, p in rows])
    db_session.commit()

    def post(txn_id, day, debit_acc, credit_acc, amount):
        m = TransactionsMaster(id=txn_id, date=datetime(2026, 1, day), notes="seed")
        db_session.add(m)
        db_session.flush()
        db_session.add(TransactionsDetail(idMaster=txn_id, acc_id=debit_acc, debit=amount, credit=0, description="seed"))
        db_session.add(TransactionsDetail(idMaster=txn_id, acc_id=credit_acc, debit=0, credit=amount, description="seed"))
        db_session.commit()

    post(1, 1, 7, 4, 500)   # rent paid from the cash box
    post(2, 2, 7, 4, 500)
    post(3, 3, 8, 5, 900)   # salaries from the bank
    post(4, 4, 4, 10, 300)  # cash sale
    return db_session
