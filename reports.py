import pandas as pd
from sqlalchemy.orm import Session, selectinload

from models import TransactionsDetail


def get_financial_summary(db: Session):
    transactions = db.query(TransactionsDetail)\
     .options(selectinload(TransactionsDetail.rsAccounts)).all()
    data = [
        {
            "credit": t.credit,
            "debit": t. debit,
            "acc_id": t.acc_id,
            "description": t.description,
            "acc_closeIn": t.rsAccounts.closeIn,
            "acc_parent_account": t.rsAccounts.parentAccount
        }
        for t in transactions
    ]

    df = pd.DataFrame(data)

    if df.empty:
        return {"Message":"لا يوجد بيانات لتحليلها"}

    df["credit"] = pd.to_numeric(df["credit"],errors="coerce").fillna(0)
    df["debit"] = pd.to_numeric(df["debit"],errors="coerce").fillna(0)

    total_income =df[df["acc_closeIn"].isin([1,2])]["credit"].sum()
    total_expense = df[df["acc_closeIn"].isin([1,2])]["debit"].sum()
    balance = total_income - total_expense

    return {
        "Total Income": total_income,
        "Total Expense": total_expense,
        "Balance": balance,
    }
