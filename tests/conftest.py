import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import Base
from models import Accounts, TransactionsDetail, TransactionsMaster


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
