from datetime import datetime, timezone, date
import enum
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Text, Enum
from sqlalchemy.orm import relationship
from app.database import Base

class InvoiceStatus(str, enum.Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(100), unique=True, index=True, nullable=False)
    customer_name = Column(String(255), index=True, nullable=False)
    customer_email = Column(String(255), nullable=True)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False)
    paid_amount = Column(Float, default=0.0, nullable=False)
    remaining_amount = Column(Float, nullable=False)
    tax_amount = Column(Float, default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(30), default=InvoiceStatus.UNPAID.value, index=True, nullable=False)
    import_source = Column(String(50), default="Manual", nullable=False)
    import_filename = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    matches = relationship("ReconciliationMatch", back_populates="invoice", cascade="all, delete-orphan")

    def update_status(self):
        """Update status based on remaining amount and current date."""
        today = date.today()
        # Round to 2 decimal places to prevent floating point inaccuracies
        rem = round(self.remaining_amount, 2)
        paid = round(self.paid_amount, 2)
        total = round(self.total_amount, 2)

        if rem <= 0.001 and paid >= total:
            self.status = InvoiceStatus.PAID.value
            self.remaining_amount = 0.0
        elif paid > 0 and rem > 0:
            if self.due_date < today:
                self.status = InvoiceStatus.OVERDUE.value
            else:
                self.status = InvoiceStatus.PARTIALLY_PAID.value
        else:
            if self.due_date < today:
                self.status = InvoiceStatus.OVERDUE.value
            else:
                self.status = InvoiceStatus.UNPAID.value
