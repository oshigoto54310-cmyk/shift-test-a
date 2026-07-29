"""履歴閲覧API（発注／数量変更／ステータス／回答／操作ログ／通知履歴）。

すべて参照のみ。削除エンドポイントは意図的に用意していない。
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..constants import (
    AUDIT_ACTION_LABELS,
    NOTIFICATION_LABELS,
    ORDER_STATUS_LABELS,
    AuditAction,
    NotificationType,
    OrderStatus,
)
from ..database import get_db
from ..deps import AccessScope, require_admin, require_hq, scope_dependency
from ..models import (
    AuditLog,
    LoginLog,
    Notification,
    NotificationLog,
    Order,
    OrderHistory,
    OrderItem,
    OrderStatusHistory,
    User,
    utcnow,
)
from ..schemas import (
    AuditLogOut,
    LoginLogOut,
    NotificationLogOut,
    NotificationOut,
    OrderHistoryOut,
    StatusHistoryOut,
)

router = APIRouter(prefix="/api/histories", tags=["履歴"])


def _label_status(code: str | None) -> str | None:
    if not code:
        return None
    try:
        return ORDER_STATUS_LABELS.get(OrderStatus(code), code)
    except ValueError:
        return code


def _user_names(db: Session, ids: set[int | None]) -> dict[int, str]:
    clean = {i for i in ids if i}
    if not clean:
        return {}
    return {u.id: u.name for u in db.query(User).filter(User.id.in_(clean)).all()}


def _scoped_order_ids(db: Session, scope: AccessScope, order_id: int | None) -> list[int] | None:
    """スコープ内の発注IDを返す。None は「全件許可」。"""
    if scope.store_id is None and scope.vendor_id is None and order_id is None:
        return None
    q = db.query(Order.id).filter(Order.deleted_at.is_(None))
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if order_id is not None:
        q = q.filter(Order.id == order_id)
    return [row[0] for row in q.all()]


@router.get("/quantity", response_model=list[OrderHistoryOut])
def quantity_histories(
    order_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=300, le=2000),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    q = db.query(OrderHistory)
    allowed = _scoped_order_ids(db, scope, order_id)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(OrderHistory.order_id.in_(allowed))
    if date_from:
        q = q.filter(OrderHistory.changed_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(OrderHistory.changed_at <= datetime.combine(date_to, datetime.max.time()))

    rows = q.order_by(OrderHistory.changed_at.desc(), OrderHistory.id.desc()).limit(limit).all()
    order_nos = {
        o.id: o.order_no
        for o in db.query(Order).filter(Order.id.in_({r.order_id for r in rows})).all()
    } if rows else {}
    item_names = {
        i.id: i.product_name
        for i in db.query(OrderItem)
        .filter(OrderItem.id.in_({r.order_item_id for r in rows if r.order_item_id}))
        .all()
    } if rows else {}
    names = _user_names(db, {r.changed_by for r in rows})

    result = []
    for r in rows:
        out = OrderHistoryOut.model_validate(r)
        out.order_no = order_nos.get(r.order_id)
        out.product_name = item_names.get(r.order_item_id)
        out.changed_by_name = names.get(r.changed_by)
        result.append(out)
    return result


@router.get("/status", response_model=list[StatusHistoryOut])
def status_histories(
    order_id: int | None = None,
    limit: int = Query(default=300, le=2000),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    q = db.query(OrderStatusHistory)
    allowed = _scoped_order_ids(db, scope, order_id)
    if allowed is not None:
        if not allowed:
            return []
        q = q.filter(OrderStatusHistory.order_id.in_(allowed))

    rows = q.order_by(OrderStatusHistory.changed_at.desc(), OrderStatusHistory.id.desc()).limit(limit).all()
    order_nos = {
        o.id: o.order_no
        for o in db.query(Order).filter(Order.id.in_({r.order_id for r in rows})).all()
    } if rows else {}
    names = _user_names(db, {r.changed_by for r in rows})

    result = []
    for r in rows:
        out = StatusHistoryOut.model_validate(r)
        out.order_no = order_nos.get(r.order_id)
        out.status_before_label = _label_status(r.status_before)
        out.status_after_label = _label_status(r.status_after)
        out.changed_by_name = names.get(r.changed_by)
        result.append(out)
    return result


@router.get("/audit", response_model=list[AuditLogOut])
def audit_logs(
    action: str | None = None,
    user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=300, le=2000),
    db: Session = Depends(get_db),
    admin: User = Depends(require_hq),
):
    """操作ログ。全社横断の記録なので本部・管理者のみ参照可。"""
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action.in_([a.strip() for a in action.split(",")]))
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)
    if date_from:
        q = q.filter(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(AuditLog.created_at <= datetime.combine(date_to, datetime.max.time()))

    rows = q.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).all()
    result = []
    for r in rows:
        out = AuditLogOut.model_validate(r)
        try:
            out.action_label = AUDIT_ACTION_LABELS.get(AuditAction(r.action), r.action)
        except ValueError:
            out.action_label = r.action
        result.append(out)
    return result


@router.get("/login", response_model=list[LoginLogOut])
def login_logs(
    limit: int = Query(default=200, le=2000),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rows = db.query(LoginLog).order_by(LoginLog.created_at.desc()).limit(limit).all()
    return [LoginLogOut.model_validate(r) for r in rows]


@router.get("/notification-logs", response_model=list[NotificationLogOut])
def notification_logs(
    limit: int = Query(default=200, le=2000),
    db: Session = Depends(get_db),
    admin: User = Depends(require_hq),
):
    rows = db.query(NotificationLog).order_by(NotificationLog.sent_at.desc()).limit(limit).all()
    return [NotificationLogOut.model_validate(r) for r in rows]


# --------------------------------------------------------------------------
# 自分あての通知
# --------------------------------------------------------------------------
notif_router = APIRouter(prefix="/api/notifications", tags=["通知"])


@notif_router.get("", response_model=list[NotificationOut])
def my_notifications(
    unread_only: bool = False,
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    q = db.query(Notification).filter(Notification.user_id == scope.user.id)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
    result = []
    for r in rows:
        out = NotificationOut.model_validate(r)
        try:
            out.type_label = NOTIFICATION_LABELS.get(NotificationType(r.type), r.type)
        except ValueError:
            out.type_label = r.type
        result.append(out)
    return result


@notif_router.get("/unread-count")
def unread_count(db: Session = Depends(get_db), scope: AccessScope = Depends(scope_dependency)):
    count = (
        db.query(Notification)
        .filter(Notification.user_id == scope.user.id, Notification.is_read.is_(False))
        .count()
    )
    return {"unread": count}


@notif_router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == scope.user.id)
        .first()
    )
    if n and not n.is_read:
        n.is_read = True
        n.read_at = utcnow()
        db.add(n)
        db.commit()
    return {"message": "既読にしました"}


@notif_router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), scope: AccessScope = Depends(scope_dependency)):
    now = utcnow()
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == scope.user.id, Notification.is_read.is_(False))
        .update({"is_read": True, "read_at": now})
    )
    db.commit()
    return {"message": "すべて既読にしました", "updated": updated}
