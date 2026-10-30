from datetime import datetime, timezone
import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, Enum
from sqlalchemy.orm import relationship
from app.database import Base

class AnomalySeverity(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class AnomalyCategory(str, enum.Enum):
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    OVERPAYMENT = "OVERPAYMENT"
    UNDERPAYMENT = "UNDERPAYMENT"
    UNMATCHED_PAYMENT = "UNMATCHED_PAYMENT"
    OVERDUE_INVOICE = "OVERDUE_INVOICE"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    UNUSUAL_AMOUNT = "UNUSUAL_AMOUNT"
    REPEATED_REFERENCE = "REPEATED_REFERENCE"
    DATE_INCONSISTENCY = "DATE_INCONSISTENCY"
    SPLIT_PAYMENT_ERROR = "SPLIT_PAYMENT_ERROR"
    ALLOCATION_OVERRUN = "ALLOCATION_OVERRUN"

class AnomalyStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"

class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"

    id = Column(Integer, primary_key=True, index=True)
    severity = Column(String(20), default=AnomalySeverity.MEDIUM.value, index=True, nullable=False)
    category = Column(String(50), index=True, nullable=False)
    title = Column(String(255), nullable=False)
    
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="SET NULL"), nullable=True, index=True)
    
    invoice_number = Column(String(100), nullable=True, index=True)
    transaction_reference = Column(String(100), nullable=True, index=True)
    customer_name = Column(String(255), nullable=True, index=True)
    amount = Column(Float, nullable=True)
    currency = Column(String(10), default="USD", nullable=False)
    
    evidence = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    suggested_action = Column(Text, nullable=False)
    
    status = Column(String(30), default=AnomalyStatus.PENDING.value, index=True, nullable=False)
    resolution_notes = Column(Text, nullable=True)
    resolved_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    invoice = relationship("Invoice", foreign_keys=[invoice_id])
    payment = relationship("Payment", foreign_keys=[payment_id])
    resolved_by_user = relationship("User", foreign_keys=[resolved_by_user_id])

