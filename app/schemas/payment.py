from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List

class PaymentBase(BaseModel):
    transaction_reference: str = Field(..., min_length=1, max_length=100)
    customer_name: Optional[str] = None
    payment_date: date
    amount: float = Field(..., gt=0)
    currency: str = Field(default="USD", max_length=10)
    payment_method: str = Field(default="Bank Transfer", max_length=50)
    bank_description: Optional[str] = None
    transaction_type: str = Field(default="CREDIT", pattern="^(CREDIT|DEBIT)$")

class PaymentCreate(PaymentBase):
    pass

class PaymentUpdate(BaseModel):
    customer_name: Optional[str] = None
    payment_date: Optional[date] = None
    amount: Optional[float] = Field(None, gt=0)
    payment_method: Optional[str] = None
    bank_description: Optional[str] = None

class PaymentResponse(PaymentBase):
    id: int
    allocated_amount: float
    unallocated_amount: float
    import_source: str
    import_filename: Optional[str] = None
    is_duplicate: bool
    is_suspicious: bool
    suspicion_reason: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class BankStatementImportResult(BaseModel):
    total_processed: int
    receipts_imported: int
    debits_excluded: int
    duplicates_detected: int
    suspicious_count: int
    errors: List[str]
