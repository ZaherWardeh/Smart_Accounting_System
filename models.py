from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, CheckConstraint
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime

class Accounts(Base):
    __tablename__ = "Accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    closeIn = Column(
        Integer,
        CheckConstraint("closeIn in (0,1,2)"),
        nullable=False,
        comment="0 For Balancesheet, 1 For Profit and lose, 2 For Trading"
    )
    parentAccount = Column(Integer, nullable=True)

    rsTransactions = relationship(
        "TransactionsDetail",
        back_populates="rsAccounts"
    )

class TransactionsMaster(Base):
    __tablename__ = "TransactionsMaster"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, nullable=False, default=datetime.utcnow)
    notes = Column(String)

    rsTransactionsMaster = relationship(
        "TransactionsDetail",
        back_populates="rsTransactionsMaster",
        cascade="all, delete-orphan"
    )

class TransactionsDetail(Base):
    __tablename__ = "TransactionsDetails"

    id = Column(Integer, primary_key=True, index=True)
    idMaster = Column(Integer, ForeignKey("TransactionsMaster.id"))
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    acc_id = Column(Integer, ForeignKey("Accounts.id"))
    description = Column(String)

    rsAccounts = relationship("Accounts", back_populates="rsTransactions")
    rsTransactionsMaster = relationship("TransactionsMaster", back_populates="rsTransactionsMaster", foreign_keys=[idMaster])
