from datetime import datetime, timezone
import enum
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Boolean, Enum
from sqlalchemy.orm import relationship
from app.database import Base

class TransactionType(str, enum.Enum):
    CREDIT = "CREDIT"   # Incoming receipt / deposit (eligible for reconciliation)
    DEBIT = "DEBIT"     # Outgoing withdrawal / charge (excluded from reconciliation)

class PaymentStatus(str, enum.Enum):
    UNMATCHED = "UNMATCHED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"
    EXCLUDED = "EXCLUDED"           # Debits or non-receipts
    SUSPICIOUS = "SUSPICIOUS"       # Needs review (e.g. duplicate payment candidate, overpayment)

class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    transaction_reference = Column(String(100), index=True, nullable=False)
    customer_name = Column(String(255), index=True, nullable=True)
    payment_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    allocated_amount = Column(Float, default=0.0, nullable=False)
    unallocated_amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    payment_method = Column(String(50), default="Bank Transfer", nullable=False)
    bank_description = Column(Text, nullable=True)
    transaction_type = Column(String(20), default=TransactionType.CREDIT.value, index=True, nullable=False)
    import_source = Column(String(50), default="Manual", nullable=False)
    import_filename = Column(String(255), nullable=True)
    
    # Flags for safety and duplicate detection
    is_duplicate = Column(Boolean, default=False, nullable=False)
    is_suspicious = Column(Boolean, default=False, nullable=False)
    suspicion_reason = Column(String(255), nullable=True)
    status = Column(String(30), default=PaymentStatus.UNMATCHED.value, index=True, nullable=False)
    
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    matches = relationship("ReconciliationMatch", back_populates="payment", cascade="all, delete-orphan")

    def update_status(self):
        """Update payment status based on transaction type, flags, and unallocated amount."""
        if self.transaction_type == TransactionType.DEBIT.value:
            self.status = PaymentStatus.EXCLUDED.value
            return

        if self.is_suspicious:
            self.status = PaymentStatus.SUSPICIOUS.value
            return

        unalloc = round(self.unallocated_amount, 2)
        alloc = round(self.allocated_amount, 2)
        amt = round(self.amount, 2)

        if unalloc <= 0.001 and alloc >= amt:
            self.status = PaymentStatus.FULLY_ALLOCATED.value
            self.unallocated_amount = 0.0
        elif alloc > 0 and unalloc > 0:
            self.status = PaymentStatus.PARTIALLY_ALLOCATED.value
        else:
            self.status = PaymentStatus.UNMATCHED.value
