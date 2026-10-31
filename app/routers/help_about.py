from pathlib import Path
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.models.user import User
from app.services.auth_service import get_current_user
from app.config import settings

router = APIRouter(tags=["Help and About"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/help", response_class=HTMLResponse)
def help_page(
    request: Request,
    current_user: User = Depends(get_current_user)
):
    return templates.TemplateResponse(request=request, name="help.html", context={
        "current_user": current_user,
        "app_name": settings.APP_NAME,
        "app_tagline": settings.APP_TAGLINE,
        "app_version": "2.4.0 (Hackathon Edition)",
        "data_dir": str(settings.DATA_DIR)
    })

