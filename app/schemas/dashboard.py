from pydantic import BaseModel
from typing import List, Dict, Any

class DashboardMetricsResponse(BaseModel):
    total_invoices_count: int
    total_invoices_amount: float
    total_payments_count: int
    total_payments_amount: float
    
    paid_count: int
    partial_count: int
    unpaid_count: int
    overdue_count: int
    
    unmatched_payments_count: int
    unmatched_payments_amount: float
    
    duplicate_candidates_count: int
    suspicious_count: int
    outstanding_amount: float
    reconciliation_rate_percent: float

class MonthlyTrendPoint(BaseModel):
    month: str
    invoices: float
    payments: float

class StatusDistribution(BaseModel):
    labels: List[str]
    counts: List[int]

class CustomerOutstandingItem(BaseModel):
    customer: str
    outstanding: float

class DashboardChartsResponse(BaseModel):
    monthly_trend: List[MonthlyTrendPoint]
    status_distribution: StatusDistribution
    payment_trend: Dict[str, Any]
    top_outstanding_customers: List[CustomerOutstandingItem]
    reconciliation_status_summary: Dict[str, int]
