from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, CheckConstraint, LargeBinary, Text, UniqueConstraint
from sqlalchemy.orm import relationship, deferred
from database import Base
from datetime import datetime

class Accounts(Base):
    __tablename__ = "Accounts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=True, unique=True, index=True)
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
    # Source document (e.g. a scanned bill) saved with the entry. The bytes are
    # deferred so listing transactions never loads the images; document_mime is
    # the cheap "has a document" marker.
    document = deferred(Column(LargeBinary, nullable=True))
    document_mime = Column(String, nullable=True)
    document_name = Column(String, nullable=True)

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


class RimaDraft(Base):
    """An operation Rima is collecting from the user (a transaction or a new
    account) that hasn't been saved yet. Lives in the DB, not memory, so an
    unanswered draft survives a restart and is never silently dropped."""
    __tablename__ = "RimaDrafts"
    __table_args__ = (UniqueConstraint("conversation_id", "kind", name="uq_rima_draft_conversation_kind"),)

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    kind = Column(String, nullable=False)  # "transaction" | "account"
    payload = Column(Text, nullable=False, default="{}")  # JSON
    status = Column(String, nullable=False, default="collecting")  # collecting | awaiting_confirmation
    confirm_request_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class RimaAttachment(Base):
    """A document image the user sent to Rima, waiting to be saved with a
    transaction (or discarded)."""
    __tablename__ = "RimaAttachments"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    mime = Column(String, nullable=False)
    filename = Column(String, nullable=True)
    data = deferred(Column(LargeBinary, nullable=False))
    facts = Column(Text, nullable=False, default="{}")  # JSON extracted by the vision call
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

