from datetime import date, datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List

class InvoiceBase(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=100)
    customer_name: str = Field(..., min_length=1, max_length=255)
    customer_email: Optional[str] = None
    invoice_date: date
    due_date: date
    total_amount: float = Field(..., gt=0)
    tax_amount: float = Field(default=0.0, ge=0)
    currency: str = Field(default="USD", max_length=10)
    description: Optional[str] = None

class InvoiceCreate(InvoiceBase):
    pass

class InvoiceUpdate(BaseModel):
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    total_amount: Optional[float] = Field(None, gt=0)
    tax_amount: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = None
    description: Optional[str] = None

class InvoiceResponse(InvoiceBase):
    id: int
    paid_amount: float
    remaining_amount: float
    status: str
    import_source: str
    import_filename: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class InvoiceImportResult(BaseModel):
    imported_count: int
    skipped_count: int
    duplicates: List[str]
    errors: List[str]
