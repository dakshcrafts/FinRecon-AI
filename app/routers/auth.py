from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserLogin, UserResponse, Token
from app.services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_current_user_optional
)
from app.services.audit_service import log_audit
from app.config import settings

router = APIRouter(tags=["Authentication"])
TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="login.html", context={"app_name": settings.APP_NAME})

@router.post("/auth/login")
async def login(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
):
    # Support both JSON payload and form-data from browser
    content_type = request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = body.get("email")
        password = body.get("password")
        is_json = True
    else:
        form = await request.form()
        email = form.get("email")
        password = form.get("password")
        is_json = False

    if not email or not password:
        if is_json:
            raise HTTPException(status_code=400, detail="Email and password are required")
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Email and password are required",
            "email": email,
            "app_name": settings.APP_NAME
        })

    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.hashed_password):
        if is_json:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Invalid email or password",
            "email": email,
            "app_name": settings.APP_NAME
        })

    if not user.is_active:
        if is_json:
            raise HTTPException(status_code=403, detail="Account is disabled")
        return templates.TemplateResponse(request=request, name="login.html", context={
            "error": "Account is disabled. Contact your administrator.",
            "app_name": settings.APP_NAME
        })

    token = create_access_token(
        data={"sub": user.email, "role": user.role, "name": user.full_name},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    log_audit(db, action="USER_LOGIN", entity_type="USER", entity_id=user.id, description=f"User {user.email} logged in successfully.", user_id=user.id)
    db.commit()

    if is_json:
        json_resp = JSONResponse(content={
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role
            }
        })
        json_resp.set_cookie(
            key="access_token",
            value=f"Bearer {token}",
            httponly=True,
            max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            samesite="lax"
        )
        return json_resp

    next_url = request.query_params.get("next", "/")
    redirect = RedirectResponse(url=next_url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key="access_token",
        value=f"Bearer {token}",
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax"
    )
    return redirect

@router.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request=request, name="register.html", context={"app_name": settings.APP_NAME})

@router.post("/auth/register")
async def register(
    request: Request,
    db: Session = Depends(get_db)
):
    content_type = request.headers.get("Content-Type", "")
    if "application/json" in content_type:
        body = await request.json()
        email = body.get("email")
        password = body.get("password")
        full_name = body.get("full_name")
        is_json = True
    else:
        form = await request.form()
        email = form.get("email")
        password = form.get("password")
        full_name = form.get("full_name")
        is_json = False

    if not email or not password or not full_name:
        err = "All fields are required"
        if is_json:
            raise HTTPException(status_code=400, detail=err)
        return templates.TemplateResponse(request=request, name="register.html", context={"error": err, "email": email, "full_name": full_name, "app_name": settings.APP_NAME})

    email_clean = email.strip().lower()
    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        err = "An account with this email already exists"
        if is_json:
            raise HTTPException(status_code=400, detail=err)
        return templates.TemplateResponse(request=request, name="register.html", context={"error": err, "email": email, "full_name": full_name, "app_name": settings.APP_NAME})

    new_user = User(
        email=email_clean,
        hashed_password=hash_password(password),
        full_name=full_name.strip(),
        role=UserRole.USER.value,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit(db, action="USER_REGISTER", entity_type="USER", entity_id=new_user.id, description=f"New user registered: {new_user.email}", user_id=new_user.id)
    db.commit()

    token = create_access_token(
        data={"sub": new_user.email, "role": new_user.role, "name": new_user.full_name},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    if is_json:
        resp = JSONResponse(content={"message": "Registration successful", "access_token": token, "user": {"id": new_user.id, "email": new_user.email, "full_name": new_user.full_name, "role": new_user.role}})
        resp.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
        return resp

    redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True, max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
    return redirect

@router.get("/auth/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        log_audit(db, action="USER_LOGOUT", entity_type="USER", entity_id=user.id, description=f"User {user.email} logged out.", user_id=user.id)
        db.commit()

    redirect = RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie(key="access_token")
    return redirect

@router.get("/api/auth/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    return current_user
