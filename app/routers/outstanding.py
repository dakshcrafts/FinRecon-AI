import logging
from typing import Optional
from pathlib import Path
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.services.auth_service import get_current_user
from app.services.outstanding_service import get_outstanding_receivables
from app.config import settings

logger = logging.getLogger("finrecon.routers.outstanding")

router = APIRouter(tags=["Outstanding Payments"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/outstanding-payments", response_class=HTMLResponse)
def outstanding_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    receivables = get_outstanding_receivables(db)
    return templates.TemplateResponse(request=request, name="outstanding.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME,
        "summary": receivables
    })

@router.get("/api/outstanding")
def get_outstanding_api(
    customer: Optional[str] = None,
    aging: Optional[str] = None,
    currency: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        data = get_outstanding_receivables(
            db,
            customer_name=customer,
            aging_category=aging,
            currency=currency,
            status_filter=status
        )
        return data
    except Exception as e:
        logger.error(f"Error fetching outstanding receivables: {e}")
        raise HTTPException(status_code=500, detail=str(e))

