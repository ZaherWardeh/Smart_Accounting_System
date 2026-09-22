from pydantic import BaseModel, ConfigDict, model_validator
from typing import Optional, List
from datetime import datetime

class AccountCreate(BaseModel):
    code: Optional[str] = None
    name: str
    closeIn: Optional[int] = 0
    parentAccount: Optional[int] = None

class AccountOut(AccountCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)

class TransactionDetailsSchema(BaseModel):
    debit: float
    credit: float
    acc_id: int
    description: str

class TransactionMasterCreate(BaseModel):
    date: Optional[datetime] = None
    notes: Optional[str] = None
    items: List[TransactionDetailsSchema]

class TransactionSchema(TransactionMasterCreate):
    id: int

    model_config = ConfigDict(from_attributes=True)

class AttachmentIn(BaseModel):
    """A document image (bill, receipt...) sent with a question."""
    data_base64: str
    mime: Optional[str] = None  # informational only; the real type is sniffed from the bytes
    filename: Optional[str] = None

class AskAIRequest(BaseModel):
    conversation_id: str
    question: str = ""
    attachment: Optional[AttachmentIn] = None

    @model_validator(mode="after")
    def _needs_text_or_attachment(self):
        if not self.question.strip() and self.attachment is None:
            raise ValueError("question or attachment is required")
        return self

class AskAIResponse(BaseModel):
    answer: str
    # unsaved operations (transaction / account drafts) still open in this conversation
    pending_drafts: List[dict] = []
