"""ダッシュボード集計。スコープに応じて自動的に絞り込まれる。"""
from __future__ import annotations

from datetime import date, time, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import APP_TZ
from ..constants import ChangeRequestStatus, OrderStatus, VENDOR_VISIBLE_STATUSES
from ..database import get_db
from ..deadlines import jst_to_utc
from ..deps import AccessScope, scope_dependency
from ..models import ChangeRequest, Order, OrderItem, utcnow
from ..schemas import DashboardOut

router = APIRouter(prefix="/api/dashboard", tags=["ダッシュボード"])


def _scoped_orders(db: Session, scope: AccessScope):
    q = db.query(Order).filter(Order.deleted_at.is_(None))
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if scope.is_vendor_user:
        q = q.filter(Order.status.in_([str(s) for s in VENDOR_VISIBLE_STATUSES]))
    return q


def _scoped_items(db: Session, scope: AccessScope):
    q = (
        db.query(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.deleted_at.is_(None), OrderItem.deleted_at.is_(None))
    )
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if scope.is_vendor_user:
        q = q.filter(Order.status.in_([str(s) for s in VENDOR_VISIBLE_STATUSES]))
    return q


@router.get("", response_model=DashboardOut)
def dashboard(
    delivery_date: date | None = None,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    now = utcnow()
    # 「本日」は日本時間で判定する
    today = now.replace(tzinfo=timezone.utc).astimezone(APP_TZ).date()
    day_start = jst_to_utc(today, time(0, 0))
    day_end = jst_to_utc(today + timedelta(days=1), time(0, 0))

    base_orders = _scoped_orders(db, scope)
    base_items = _scoped_items(db, scope)
    if delivery_date:
        base_orders = base_orders.filter(Order.delivery_date == delivery_date)
        base_items = base_items.filter(Order.delivery_date == delivery_date)

    # 本日締め件数（本日中に最終締めを迎える発注）
    today_deadline = (
        _scoped_orders(db, scope)
        .filter(
            Order.deadline_at >= day_start,
            Order.deadline_at < day_end,
            Order.status != str(OrderStatus.CANCELLED),
        )
        .count()
    )

    unconfirmed = base_orders.filter(
        Order.status.in_([str(OrderStatus.DRAFT), str(OrderStatus.PLANNED)])
    ).count()

    vendor_pending = base_items.filter(
        OrderItem.status == str(OrderStatus.VENDOR_PENDING)
    ).count()
    shortage = base_items.filter(OrderItem.status == str(OrderStatus.SHORTAGE)).count()
    partial = base_items.filter(OrderItem.status == str(OrderStatus.PARTIAL)).count()
    substitute = base_items.filter(OrderItem.status == str(OrderStatus.SUBSTITUTE)).count()

    # 回答期限超過（回答期限を過ぎてもベンダー未確認のもの）
    reply_overdue = (
        _scoped_items(db, scope)
        .filter(
            OrderItem.status == str(OrderStatus.VENDOR_PENDING),
            Order.reply_deadline_at.isnot(None),
            Order.reply_deadline_at < now,
        )
        .count()
    )

    cr_q = (
        db.query(func.count(ChangeRequest.id))
        .join(Order, Order.id == ChangeRequest.order_id)
        .filter(
            ChangeRequest.status == str(ChangeRequestStatus.PENDING),
            Order.deleted_at.is_(None),
        )
    )
    if scope.store_id is not None:
        cr_q = cr_q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        cr_q = cr_q.filter(Order.vendor_id == scope.vendor_id)
    change_requests = cr_q.scalar() or 0

    return DashboardOut(
        today_deadline_count=today_deadline,
        unconfirmed_count=unconfirmed,
        vendor_pending_count=vendor_pending,
        shortage_count=shortage,
        partial_count=partial,
        substitute_count=substitute,
        change_request_count=change_requests,
        reply_overdue_count=reply_overdue,
        delivery_date=delivery_date,
        store_id=scope.store_id,
        vendor_id=scope.vendor_id,
    )
