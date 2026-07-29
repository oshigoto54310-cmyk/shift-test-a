"""ログイン・ログアウト・パスワード再設定。"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action, log_login
from ..config import settings
from ..constants import ROLE_LABELS, AuditAction, CROSS_TENANT_ROLES, RoleCode
from ..database import get_db
from ..deps import get_current_user
from ..models import User, utcnow
from ..notify import _send_mail
from ..schemas import (
    LoginRequest,
    MeResponse,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from ..security import (
    create_access_token,
    generate_csrf_token,
    generate_reset_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["認証"])

# ログイン失敗時は「メールが存在しない」と「パスワードが違う」を区別しない
GENERIC_LOGIN_ERROR = "メールアドレスまたはパスワードが正しくありません"


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    max_age = settings.session_minutes * 60
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    # CSRF トークンは JS から読めるようにする（double submit cookie 方式）
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _me_payload(user: User) -> MeResponse:
    role_code = user.role.code
    can_switch = role_code in {str(r) for r in CROSS_TENANT_ROLES}
    return MeResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        role_code=role_code,
        role_label=ROLE_LABELS.get(RoleCode(role_code), role_code),
        store_id=user.store_id,
        store_name=user.store.name if user.store else None,
        vendor_id=user.vendor_id,
        vendor_name=user.vendor.name if user.vendor else None,
        can_switch_vendor=can_switch,
        can_switch_store=can_switch,
        last_login_at=user.last_login_at,
    )


@router.post("/login", response_model=MeResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    email = payload.email.lower().strip()
    user = (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.store), joinedload(User.vendor))
        .filter(User.email == email)
        .first()
    )

    if user is None or user.deleted_at is not None:
        log_login(db, email, False, failure_reason="ユーザーが存在しません", request=request)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    now = utcnow()
    if user.locked_until and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60) + 1
        log_login(
            db, email, False, user_id=user.id, failure_reason="ロック中", request=request
        )
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"ログイン失敗が続いたためロックされています。約{remaining}分後に再試行してください。",
        )

    if not user.is_active:
        log_login(db, email, False, user_id=user.id, failure_reason="停止中", request=request)
        raise HTTPException(status.HTTP_403_FORBIDDEN, "このアカウントは停止されています")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        reason = "パスワード不一致"
        if user.failed_login_count >= settings.max_login_failures:
            user.locked_until = now + timedelta(minutes=settings.lock_minutes)
            user.failed_login_count = 0
            reason = "パスワード不一致（ロック発動）"
        db.add(user)
        log_login(db, email, False, user_id=user.id, failure_reason=reason, request=request)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, GENERIC_LOGIN_ERROR)

    # 認証成功
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    db.add(user)

    token = create_access_token(user.id, user.role.code)
    csrf_token = generate_csrf_token()
    _set_session_cookies(response, token, csrf_token)

    log_login(db, email, True, user_id=user.id, request=request, commit=False)
    log_action(db, user, AuditAction.LOGIN, target_type="user", target_id=user.id, request=request)
    db.commit()

    return _me_payload(user)


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    log_action(db, user, AuditAction.LOGOUT, target_type="user", target_id=user.id, request=request)
    db.commit()
    response.delete_cookie(settings.cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"message": "ログアウトしました"}


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return _me_payload(user)


@router.post("/password-reset/request")
def password_reset_request(
    payload: PasswordResetRequest, request: Request, db: Session = Depends(get_db)
):
    """再設定トークンを発行する。

    アカウントの存在有無を漏らさないよう、結果は常に同じメッセージを返す。
    """
    email = payload.email.lower().strip()
    user = db.query(User).filter(User.email == email, User.deleted_at.is_(None)).first()
    if user and user.is_active:
        token = generate_reset_token()
        user.password_reset_token = token
        user.password_reset_expires = utcnow() + timedelta(hours=1)
        db.add(user)
        db.commit()
        _send_mail(
            user.email,
            "パスワード再設定のご案内",
            f"以下のトークンでパスワードを再設定してください（1時間有効）。\n\nトークン: {token}\n",
        )
    return {"message": "パスワード再設定の手順をメールで送信しました（登録がある場合）"}


@router.post("/password-reset/confirm")
def password_reset_confirm(
    payload: PasswordResetConfirm, request: Request, db: Session = Depends(get_db)
):
    user = (
        db.query(User)
        .filter(User.password_reset_token == payload.token, User.deleted_at.is_(None))
        .first()
    )
    if (
        user is None
        or user.password_reset_expires is None
        or user.password_reset_expires < utcnow()
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "トークンが無効か期限切れです")

    user.password_hash = hash_password(payload.new_password)
    user.password_reset_token = None
    user.password_reset_expires = None
    user.failed_login_count = 0
    user.locked_until = None
    db.add(user)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="user_password", target_id=user.id, request=request)
    db.commit()
    return {"message": "パスワードを再設定しました"}


@router.post("/password")
def change_password(
    payload: PasswordChange,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "現在のパスワードが正しくありません")
    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="user_password", target_id=user.id, request=request)
    db.commit()
    return {"message": "パスワードを変更しました"}
