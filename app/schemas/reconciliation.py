from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any

class ReconciliationRunRequest(BaseModel):
    auto_approve_high: bool = False
    re_evaluate_all: bool = False

class MatchExplanationDetails(BaseModel):
    invoice_number_score: float = 0.0
    customer_name_score: float = 0.0
    amount_score: float = 0.0
    date_score: float = 0.0
    customer_similarity_ratio: float = 0.0
    days_difference: int = 0
    strategy: str = ""
    notes: List[str] = []

class ReconciliationMatchResponse(BaseModel):
    id: int
    invoice_id: int
    payment_id: int
    allocated_amount: float
    confidence_score: float
    confidence_tier: str
    status: str
    strategy_applied: str
    explanation: str
    match_details: Optional[Dict[str, Any]] = None
    
    # Nested minimal details for UI display
    invoice_number: Optional[str] = None
    invoice_customer: Optional[str] = None
    invoice_total: Optional[float] = None
    invoice_remaining: Optional[float] = None
    
    payment_reference: Optional[str] = None
    payment_customer: Optional[str] = None
    payment_amount: Optional[float] = None
    payment_unallocated: Optional[float] = None
    payment_bank_desc: Optional[str] = None
    
    approved_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class ManualAllocationRequest(BaseModel):
    invoice_id: int
    payment_id: int
    allocated_amount: float = Field(..., gt=0)
    notes: Optional[str] = None

class MatchActionRequest(BaseModel):
    reason: Optional[str] = None

class BulkApproveRequest(BaseModel):
    match_ids: Optional[List[int]] = None  # None or empty means all pending HIGH confidence matches

class ReconciliationSettingsUpdate(BaseModel):
    weight_invoice_number: float = Field(..., ge=0, le=100)
    weight_customer_name: float = Field(..., ge=0, le=100)
    weight_amount: float = Field(..., ge=0, le=100)
    weight_date_proximity: float = Field(..., ge=0, le=100)
    auto_match_threshold: float = Field(..., ge=0, le=100)
    review_queue_threshold: float = Field(..., ge=0, le=100)
    ambiguity_margin: float = Field(default=5.0, ge=0, le=50)
    auto_match_enabled: bool = True
    date_tolerance_days: int = Field(default=30, ge=1, le=365)

class ReconciliationSettingsResponse(BaseModel):
    weight_invoice_number: float
    weight_customer_name: float
    weight_amount: float
    weight_date_proximity: float
    auto_match_threshold: float
    review_queue_threshold: float
    ambiguity_margin: float = 5.0
    auto_match_enabled: bool
    date_tolerance_days: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
