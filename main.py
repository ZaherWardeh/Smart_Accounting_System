import os
from typing import List, Optional

from fastapi import FastAPI, Depends, status, HTTPException, Body, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, joinedload
from database import sessionLocal, engine, Base, ensure_columns
from models import Accounts, TransactionsMaster, TransactionsDetail
from schemas import AccountCreate, AccountOut, TransactionMasterCreate, TransactionSchema, AskAIRequest, AskAIResponse
from datetime import datetime
from reports import get_financial_summary
from tools import get_chart_of_accounts, get_account_transactions, get_account_balance
from graph import run_agent, is_llm_connected, conversation_lock, record_event
from drafts import KIND_ACCOUNT, KIND_TRANSACTION, cancel_draft, confirm_draft, list_pending_drafts
import documents

app = FastAPI()

# إنشاء الجداول في قاعدة البيانات
ensure_columns()  # add columns introduced after the first release to older databases
Base.metadata.create_all(bind=engine)
with sessionLocal() as _startup_db:
    try:
        documents.cleanup_stale_attachments(_startup_db)  # uploads nobody used within a week
    except Exception as _e:  # housekeeping must never stop the server from starting
        print(f"Attachment cleanup skipped: {_e}")

# The built-in website is optional: SERVE_WEB=0 runs the REST API only (e.g. when the
# only client is the mobile app and the backend is exposed through a tunnel).
SERVE_WEB = os.getenv("SERVE_WEB", "1") != "0"

if SERVE_WEB:
    app.mount("/static", StaticFiles(directory="static"), name="static")

# دالة لجلب جلسة قاعدة البيانات
def get_db():
    db = sessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health():
    return {"status": "ok", "llm_connected": is_llm_connected()}

if SERVE_WEB:
    @app.get("/")
    def home():
        return FileResponse("static/index.html")

    @app.get("/accounts")
    def accounts_page():
        return FileResponse("static/accounts.html")

    @app.get("/transactions")
    def transactions_page():
        return FileResponse("static/transactions.html")

    @app.get("/reports")
    def reports_page():
        return FileResponse("static/reports.html")

    @app.get("/chat")
    def chat_page():
        return FileResponse("static/chat.html")

# حسابات
@app.get("/accounts/")
def get_accounts(db: Session = Depends(get_db)):
    return db.query(Accounts).all()

@app.get("/accounts/{id}")
def get_account(id: int, db: Session = Depends(get_db)):
    account = db.query(Accounts).filter(Accounts.id == id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountOut.model_validate(account)

@app.post("/accounts/", status_code=status.HTTP_201_CREATED)
def create_account(account: AccountCreate = Body(...), db: Session = Depends(get_db)):
    db_account = Accounts(
        code=account.code,
        name=account.name,
        closeIn=account.closeIn,
        parentAccount=account.parentAccount
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return AccountOut.model_validate(db_account)

@app.put("/accounts/", status_code=status.HTTP_202_ACCEPTED)
def update_account(account: AccountOut = Body(...), db: Session = Depends(get_db)):
    db_account = db.query(Accounts).filter(Accounts.id == account.id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
    db_account.code = account.code
    db_account.name = account.name
    db_account.closeIn = account.closeIn
    db_account.parentAccount = account.parentAccount
    db.commit()
    db.refresh(db_account)
    return AccountOut.model_validate(db_account)

@app.delete("/accounts/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(id: int, db: Session = Depends(get_db)):
    db_account = db.query(Accounts).filter(Accounts.id == id).first()
    if not db_account:
        raise HTTPException(status_code=404, detail="Account not found")
    has_children = db.query(Accounts).filter(Accounts.parentAccount == id).first() is not None
    if has_children:
        raise HTTPException(status_code=409, detail="Cannot delete a master account that has child accounts")
    has_transactions = db.query(TransactionsDetail).filter(TransactionsDetail.acc_id == id).first() is not None
    if has_transactions:
        raise HTTPException(status_code=409, detail="Cannot delete an account that has transactions posted to it")
    db.delete(db_account)
    db.commit()

# معاملات
@app.get("/transactions/")
def get_transactions(db: Session = Depends(get_db)):
    transactions = db.query(TransactionsMaster)\
        .options(joinedload(TransactionsMaster.rsTransactionsMaster)
                 .joinedload(TransactionsDetail.rsAccounts)).all()
    result = []
    for transaction in transactions:
        result.append({
            "id": transaction.id,
            "date": transaction.date,
            "notes": transaction.notes,
            "has_document": transaction.document_mime is not None,
            "details": [
                {
                    "id": detail.id,
                    "debit": detail.debit,
                    "credit": detail.credit,
                    "description": detail.description,
                    "acc_id": detail.acc_id,
                    "acc_name": detail.rsAccounts.name if detail.rsAccounts else None
                } for detail in transaction.rsTransactionsMaster
            ]
        })
    return result

@app.get("/transactions/{id}")
def get_transaction(id: int, db: Session = Depends(get_db)):
    transaction = db.query(TransactionsMaster)\
        .options(joinedload(TransactionsMaster.rsTransactionsMaster)
                 .joinedload(TransactionsDetail.rsAccounts))\
        .filter(TransactionsMaster.id == id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {
        "id": transaction.id,
        "date": transaction.date,
        "notes": transaction.notes,
        "has_document": transaction.document_mime is not None,
        "details": [
            {
                "id": detail.id,
                "debit": detail.debit,
                "credit": detail.credit,
                "description": detail.description,
                "acc_id": detail.acc_id,
                "acc_name": detail.rsAccounts.name if detail.rsAccounts else None
            } for detail in transaction.rsTransactionsMaster
        ]
    }

@app.get("/transactions/{id}/document")
def get_transaction_document(id: int, db: Session = Depends(get_db)):
    """The source document (image) saved with an entry."""
    transaction = db.query(TransactionsMaster).filter(TransactionsMaster.id == id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.document_mime is None or not transaction.document:
        raise HTTPException(status_code=404, detail="This transaction has no document")
    headers = {"Cache-Control": "private, max-age=3600"}
    if transaction.document_name:
        headers["Content-Disposition"] = f'inline; filename="{transaction.document_name}"'
    return Response(content=transaction.document, media_type=transaction.document_mime, headers=headers)

def CheckBalance(transaction: TransactionMasterCreate) -> bool:
    total_debits = 0
    total_credits = 0
    for i in transaction.items:
        total_debits += i.debit
        total_credits += i.credit
    # compare in cents so decimal amounts (0.1 + 0.2 vs 0.3) don't fail on float noise
    return round(total_debits, 2) == round(total_credits, 2)

@app.post("/transactions/", status_code=status.HTTP_201_CREATED)
def create_Transaction(transaction: TransactionMasterCreate = Body(...), db: Session = Depends(get_db)):
    if not CheckBalance(transaction):
        raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="Transaction not balanced")
    db_transaction = TransactionsMaster(
        date=transaction.date or datetime.utcnow(),
        notes=transaction.notes
    )
    for item in transaction.items:
        db_item = TransactionsDetail(
            debit=item.debit,
            credit=item.credit,
            acc_id=item.acc_id,
            description=item.description
        )
        db_transaction.rsTransactionsMaster.append(db_item)
    db.add(db_transaction)
    db.commit()
    db.refresh(db_transaction)
    return {
        "id": db_transaction.id,
        "date": db_transaction.date,
        "notes": db_transaction.notes,
        "items": [
            {
                "id": detail.id,
                "debit": detail.debit,
                "credit": detail.credit,
                "description": detail.description,
                "acc_id": detail.acc_id,
                "description": detail.description,
                "acc_name": detail.rsAccounts.name if detail.rsAccounts else None
            }
            for detail in db_transaction.rsTransactionsMaster
        ]
    }

@app.put("/transactions/", status_code=status.HTTP_201_CREATED)
def update_transaction(transaction: TransactionSchema = Body(...), db: Session = Depends(get_db)):
    if not CheckBalance(transaction):
        raise HTTPException(status_code=status.HTTP_406_NOT_ACCEPTABLE, detail="Transaction not balanced")
    db_transaction = db.query(TransactionsMaster).filter(TransactionsMaster.id == transaction.id).first()
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db_transaction.notes = transaction.notes
    db_transaction.date = transaction.date or datetime.utcnow()
    db_transaction.rsTransactionsMaster.clear()
    for item in transaction.items:
        db_item = TransactionsDetail(
            debit=item.debit,
            credit=item.credit,
            acc_id=item.acc_id,
            description=item.description
        )
        db_transaction.rsTransactionsMaster.append(db_item)
    db.commit()
    db.refresh(db_transaction)
    return {
        "id": db_transaction.id,
        "date": db_transaction.date,
        "notes": db_transaction.notes,
        "items": [
            {
                "id": detail.id,
                "debit": detail.debit,
                "credit": detail.credit,
                "description": detail.description,
                "acc_id": detail.acc_id,
                "description": detail.description,
                "acc_name": detail.rsAccounts.name if detail.rsAccounts else None
            }
            for detail in db_transaction.rsTransactionsMaster
        ]
    }

@app.delete("/transactions/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(id: int, db: Session = Depends(get_db)):
    db_transaction = db.query(TransactionsMaster).filter(TransactionsMaster.id == id).first()
    if not db_transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(db_transaction)
    db.commit()

#تقارير + ذكاء صناعي
@app.get("/reports/summery")
def get_summery(db : Session = Depends(get_db)):
    return get_financial_summary(db)

@app.get("/reports/chart-of-accounts")
def get_chart_of_accounts_report(db: Session = Depends(get_db)):
    return get_chart_of_accounts(db)

@app.get("/reports/statement/{acc_id}")
def get_statement_of_account(
    acc_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    if not db.query(Accounts).filter(Accounts.id == acc_id).first():
        raise HTTPException(status_code=404, detail="Account not found")
    return get_account_transactions(db, acc_id, date_from, date_to)

@app.get("/reports/balance")
def get_balance_report(
    acc_ids: List[int] = Query(...),
    as_of_date: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return get_account_balance(db, acc_ids, as_of_date, date_from, date_to)

@app.post("/reports/ask_ai", response_model=AskAIResponse)
def ask_ai(request: AskAIRequest = Body(...), db: Session = Depends(get_db)):
    attachment = None
    if request.attachment is not None:
        try:
            mime, data = documents.decode_attachment(request.attachment.data_base64, request.attachment.mime)
        except documents.AttachmentError as e:
            code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if "too large" in str(e) else status.HTTP_400_BAD_REQUEST
            raise HTTPException(status_code=code, detail=str(e))
        attachment = {"mime": mime, "data": data, "filename": request.attachment.filename}
    answer = run_agent(db, request.conversation_id, request.question, attachment)
    return AskAIResponse(answer=answer, pending_drafts=list_pending_drafts(db, request.conversation_id))


# ---- unsaved operations Rima is collecting (transaction / account drafts) ----
# Deterministic counterparts of "yes, save it" / "cancel it": a real button press
# from the app or website, not the model interpreting a sentence.

def _draft_kind(kind: str) -> str:
    if kind not in (KIND_TRANSACTION, KIND_ACCOUNT):
        raise HTTPException(status_code=404, detail="Unknown draft type")
    return kind


@app.get("/drafts/{conversation_id}")
def get_drafts(conversation_id: str, db: Session = Depends(get_db)):
    return list_pending_drafts(db, conversation_id)


@app.post("/drafts/{conversation_id}/{kind}/confirm")
def confirm_pending_draft(conversation_id: str, kind: str, db: Session = Depends(get_db)):
    kind = _draft_kind(kind)
    with conversation_lock(conversation_id):
        result = confirm_draft(db, conversation_id, kind)
        if result.get("ok"):
            what = (
                f"entry #{result['transaction_id']} was saved" if kind == KIND_TRANSACTION
                else f"account {result['account']['code'] or ''} {result['account']['name']} was created"
            )
            record_event(conversation_id, f"the user pressed Confirm and the {what}; that draft is finished")
    if not result.get("ok"):
        code = {"no_draft": 404, "incomplete": 409}.get(result.get("error"), 422)
        raise HTTPException(status_code=code, detail=result)
    result["pending_drafts"] = list_pending_drafts(db, conversation_id)
    return result


@app.post("/drafts/{conversation_id}/{kind}/cancel")
def cancel_pending_draft(conversation_id: str, kind: str, db: Session = Depends(get_db)):
    kind = _draft_kind(kind)
    with conversation_lock(conversation_id):
        result = cancel_draft(db, conversation_id, kind)
        if result.get("cancelled"):
            record_event(conversation_id, f"the user pressed Abort and the {kind} draft was discarded")
    result["pending_drafts"] = list_pending_drafts(db, conversation_id)
    return result