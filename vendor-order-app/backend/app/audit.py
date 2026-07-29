"""操作ログ記録。ログは削除しない（削除APIを設けない）。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, LoginLog, User


def _client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()[:60]
    return request.client.host if request.client else None


def _user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    return (request.headers.get("User-Agent") or "")[:300] or None


def log_action(
    db: Session,
    user: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: Any = None,
    detail: dict | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else None,
        role_code=user.role.code if user else None,
        store_id=user.store_id if user else None,
        vendor_id=user.vendor_id if user else None,
        action=str(action),
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=json.dumps(detail, ensure_ascii=False, default=str) if detail else None,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry


def log_login(
    db: Session,
    email: str,
    success: bool,
    *,
    user_id: int | None = None,
    failure_reason: str | None = None,
    request: Request | None = None,
    commit: bool = True,
) -> LoginLog:
    entry = LoginLog(
        user_id=user_id,
        email=email[:255],
        success=success,
        failure_reason=failure_reason,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()
    return entry
