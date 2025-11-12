from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class AccountCreate(BaseModel):
    name: str
    closeIn: Optional[int] = 0
    parentAccount: Optional[int] = None

class AccountOut(AccountCreate):
    id: int

    class Config:
        orm_mode = True

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

    class Config:
        orm_mode = True
