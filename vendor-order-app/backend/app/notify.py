"""アプリ内通知＋メール通知。

- dedup_key により同じ通知を重複送信しない（user_id + dedup_key に UNIQUE 制約）。
- 送信結果は notification_logs に必ず残す。
- 将来 PWA プッシュを追加する場合は _dispatch に channel="PUSH" を足すだけで済む構造にしている。
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .config import settings
from .constants import CROSS_TENANT_ROLES, NotificationType, RoleCode
from .models import Notification, NotificationLog, Order, User

logger = logging.getLogger(__name__)


def _send_mail(to_address: str, subject: str, body: str) -> tuple[str, str | None]:
    """(status, error) を返す。SMTP未設定時は SKIPPED。"""
    if not settings.mail_enabled or not settings.smtp_host:
        return "SKIPPED", None
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_address
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return "SENT", None
    except Exception as exc:  # pragma: no cover - 外部依存
        logger.warning("メール送信に失敗しました: %s", exc)
        return "FAILED", str(exc)[:500]


def notify_users(
    db: Session,
    users: list[User],
    *,
    notification_type: NotificationType | str,
    title: str,
    body: str,
    dedup_key: str,
    order_id: int | None = None,
    order_item_id: int | None = None,
    commit: bool = False,
) -> list[Notification]:
    """対象ユーザーへ通知を作成する。既に同じ dedup_key があればスキップ。"""
    created: list[Notification] = []
    ntype = str(notification_type)

    for user in users:
        if user is None or not user.is_active or user.deleted_at is not None:
            continue

        exists = (
            db.query(Notification.id)
            .filter(Notification.user_id == user.id, Notification.dedup_key == dedup_key)
            .first()
        )
        if exists:
            db.add(
                NotificationLog(
                    notification_id=exists[0],
                    user_id=user.id,
                    channel="APP",
                    type=ntype,
                    status="SKIPPED",
                    error="重複のため送信しません",
                    dedup_key=dedup_key,
                )
            )
            continue

        notification = Notification(
            user_id=user.id,
            type=ntype,
            title=title[:200],
            body=body,
            order_id=order_id,
            order_item_id=order_item_id,
            dedup_key=dedup_key[:200],
        )
        db.add(notification)
        db.flush()
        created.append(notification)

        db.add(
            NotificationLog(
                notification_id=notification.id,
                user_id=user.id,
                channel="APP",
                to_address=user.email,
                type=ntype,
                status="SENT",
                dedup_key=dedup_key,
            )
        )

        mail_status, mail_error = _send_mail(user.email, title, body)
        db.add(
            NotificationLog(
                notification_id=notification.id,
                user_id=user.id,
                channel="EMAIL",
                to_address=user.email,
                type=ntype,
                status=mail_status,
                error=mail_error,
                dedup_key=dedup_key,
            )
        )

    if commit:
        db.commit()
    else:
        db.flush()
    return created


# --------------------------------------------------------------------------
# 宛先の組み立て
# --------------------------------------------------------------------------
def _active_users(db: Session):
    return db.query(User).filter(User.is_active.is_(True), User.deleted_at.is_(None))


def hq_users(db: Session) -> list[User]:
    codes = [str(r) for r in CROSS_TENANT_ROLES]
    return [u for u in _active_users(db).all() if u.role.code in codes]


def store_users(db: Session, store_id: int) -> list[User]:
    return [
        u
        for u in _active_users(db).filter(User.store_id == store_id).all()
        if u.role.code == RoleCode.STORE
    ]


def vendor_users(db: Session, vendor_id: int) -> list[User]:
    return [
        u
        for u in _active_users(db).filter(User.vendor_id == vendor_id).all()
        if u.role.code == RoleCode.VENDOR
    ]


def order_stakeholders(
    db: Session, order: Order, *, include_store=True, include_vendor=True, include_hq=True
) -> list[User]:
    users: list[User] = []
    seen: set[int] = set()
    groups = []
    if include_store:
        groups.append(store_users(db, order.store_id))
    if include_vendor:
        groups.append(vendor_users(db, order.vendor_id))
    if include_hq:
        groups.append(hq_users(db))
    for group in groups:
        for u in group:
            if u.id not in seen:
                seen.add(u.id)
                users.append(u)
    return users
