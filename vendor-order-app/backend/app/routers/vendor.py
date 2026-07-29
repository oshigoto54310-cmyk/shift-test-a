"""ベンダー回答API と ベンダー向け集計。

ベンダーユーザーは自ベンダーの発注にのみ回答できる。
本部・管理者は閲覧と代替提案の承認を行う。
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..constants import (
    ORDER_STATUS_LABELS,
    RESPONSE_TYPE_LABELS,
    AuditAction,
    NotificationType,
    OrderStatus,
    ResponseType,
    RoleCode,
    VENDOR_VISIBLE_STATUSES,
)
from ..database import get_db
from ..deps import (
    AccessScope,
    forbidden,
    get_current_user,
    require_hq,
    scope_dependency,
)
from ..models import Order, OrderItem, Store, User, VendorResponse, utcnow
from ..notify import hq_users, notify_users, store_users
from ..schemas import SubstituteDecision, VendorAckRequest, VendorResponseIn, VendorResponseOut
from ..services import (
    consume_idempotency_token,
    get_item_for_user,
    get_order_for_user,
    recalc_order_status,
    scoped_order_query,
    set_item_status,
)

router = APIRouter(prefix="/api/vendor", tags=["ベンダー回答"])


def _assert_can_respond(user: User, order: Order) -> None:
    """回答できるのは自ベンダーのベンダーユーザーのみ。"""
    if user.role.code != RoleCode.VENDOR:
        raise forbidden("ベンダー担当者のみ回答できます")
    if user.vendor_id != order.vendor_id:
        raise forbidden("他ベンダーの発注には回答できません")
    if order.status not in {str(s) for s in VENDOR_VISIBLE_STATUSES}:
        raise HTTPException(status.HTTP_409_CONFLICT, "確定前の発注には回答できません")


def _response_out(r: VendorResponse, responder_name: str | None = None) -> VendorResponseOut:
    out = VendorResponseOut.model_validate(r)
    out.response_label = RESPONSE_TYPE_LABELS.get(ResponseType(r.response_type), r.response_type)
    out.responder_name = responder_name
    out.sub_cost = float(r.sub_cost) if r.sub_cost is not None else None
    return out


# --------------------------------------------------------------------------
# 受注確認
# --------------------------------------------------------------------------
@router.post("/ack")
def acknowledge_order(
    payload: VendorAckRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """受注確認。発注を見た、という意思表示。"""
    order = get_order_for_user(db, payload.order_id, user)
    _assert_can_respond(user, order)

    changed = 0
    for item in [i for i in order.items if i.deleted_at is None]:
        if item.status == str(OrderStatus.VENDOR_PENDING):
            set_item_status(db, order, item, str(OrderStatus.VENDOR_ACK), user, note="受注確認")
            changed += 1
    recalc_order_status(db, order, user)

    log_action(db, user, AuditAction.VENDOR_RESPONSE, target_type="order", target_id=order.id,
               detail={"操作": "受注確認", "order_no": order.order_no, "件数": changed},
               request=request)
    notify_users(
        db,
        store_users(db, order.store_id) + hq_users(db),
        notification_type=NotificationType.ORDER_CONFIRMED,
        title=f"受注確認 {order.order_no}",
        body=f"{order.vendor.name} が受注を確認しました。",
        dedup_key=f"vendor_ack:{order.id}",
        order_id=order.id,
    )
    db.commit()
    return {"message": "受注確認しました", "updated_items": changed}


# --------------------------------------------------------------------------
# 明細ごとの回答
# --------------------------------------------------------------------------
@router.post("/responses", response_model=VendorResponseOut, status_code=status.HTTP_201_CREATED)
def create_response(
    payload: VendorResponseIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order, item = get_item_for_user(db, payload.order_item_id, user)
    _assert_can_respond(user, order)
    consume_idempotency_token(db, user, payload.client_token, "vendor_response")

    if payload.response_type not in {str(t) for t in ResponseType}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "回答区分が不正です")
    rtype = ResponseType(payload.response_type)

    if item.status == str(OrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT, "取消済みの明細には回答できません")

    deliverable = payload.deliverable_qty
    shortage = None

    # --- 回答区分ごとの必須チェック ---
    if rtype == ResponseType.FULL:
        deliverable = item.quantity
        shortage = 0
    elif rtype == ResponseType.PARTIAL:
        if deliverable is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "一部納品では納品可能数量が必須です")
        if deliverable >= item.quantity:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "一部納品の納品可能数量は発注数量より少なくしてください",
            )
        if deliverable <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "納品可能数量が0の場合は欠品で回答してください"
            )
        if not (payload.reason or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "一部納品では理由が必須です")
        shortage = item.quantity - deliverable
    elif rtype == ResponseType.SHORTAGE:
        if not (payload.shortage_reason or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "欠品では欠品理由が必須です")
        if payload.next_available_date and payload.next_available_date < date.today():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "次回納品可能日に過去の日付は指定できません"
            )
        deliverable = 0
        shortage = item.quantity
    elif rtype == ResponseType.SUBSTITUTE:
        if not (payload.sub_product_name or "").strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "代替提案では代替商品名が必須です")
        if payload.sub_deliverable_qty is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "代替提案では納品可能数量が必須です")
        if payload.sub_delivery_date and payload.sub_delivery_date < date.today():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "代替商品の納品可能日に過去の日付は指定できません"
            )
        deliverable = payload.deliverable_qty or 0
        if deliverable > item.quantity:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"納品可能数量が発注数量（{item.quantity}）を超えています",
            )
        if payload.sub_deliverable_qty > item.quantity:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"代替商品の納品可能数量が発注数量（{item.quantity}）を超えています",
            )
        shortage = max(item.quantity - deliverable, 0)

    # 直前の回答を履歴として残し、最新フラグを付け替える
    db.query(VendorResponse).filter(
        VendorResponse.order_item_id == item.id, VendorResponse.is_latest.is_(True)
    ).update({"is_latest": False})

    response = VendorResponse(
        order_id=order.id,
        order_item_id=item.id,
        vendor_id=order.vendor_id,
        response_type=str(rtype),
        ordered_qty=item.quantity,
        deliverable_qty=deliverable,
        shortage_qty=shortage,
        reason=payload.reason,
        shortage_reason=payload.shortage_reason,
        next_available_date=payload.next_available_date,
        has_substitute=payload.has_substitute or rtype == ResponseType.SUBSTITUTE,
        sub_product_name=payload.sub_product_name,
        sub_jan_code=payload.sub_jan_code,
        sub_spec=payload.sub_spec,
        sub_cost=payload.sub_cost,
        sub_deliverable_qty=payload.sub_deliverable_qty,
        sub_delivery_date=payload.sub_delivery_date,
        sub_comment=payload.sub_comment,
        comment=payload.comment,
        responder_id=user.id,
        is_latest=True,
    )
    db.add(response)
    db.flush()

    # --- 明細ステータスと確定数量を更新 ---
    status_map = {
        ResponseType.FULL: OrderStatus.DELIVERED,
        ResponseType.PARTIAL: OrderStatus.PARTIAL,
        ResponseType.SHORTAGE: OrderStatus.SHORTAGE,
        ResponseType.SUBSTITUTE: OrderStatus.SUBSTITUTE,
        ResponseType.CHECKING: OrderStatus.VENDOR_ACK,
        ResponseType.CONSULT: OrderStatus.VENDOR_ACK,
    }
    new_status = status_map[rtype]
    if rtype in {ResponseType.FULL, ResponseType.PARTIAL, ResponseType.SHORTAGE}:
        item.confirmed_quantity = deliverable
    item.updated_by = user.id
    db.add(item)
    set_item_status(db, order, item, str(new_status), user, note=f"ベンダー回答: {RESPONSE_TYPE_LABELS[rtype]}")
    recalc_order_status(db, order, user)

    # --- 操作ログ・通知 ---
    action = {
        ResponseType.SHORTAGE: AuditAction.VENDOR_SHORTAGE,
        ResponseType.SUBSTITUTE: AuditAction.VENDOR_SUBSTITUTE,
    }.get(rtype, AuditAction.VENDOR_RESPONSE)
    log_action(db, user, action, target_type="order_item", target_id=item.id,
               detail={"order_no": order.order_no, "商品": item.product_name,
                       "回答": RESPONSE_TYPE_LABELS[rtype], "納品可能数量": deliverable},
               request=request)

    notify_type = {
        ResponseType.PARTIAL: NotificationType.PARTIAL_DELIVERY,
        ResponseType.SHORTAGE: NotificationType.SHORTAGE,
        ResponseType.SUBSTITUTE: NotificationType.SUBSTITUTE,
        ResponseType.FULL: NotificationType.DELIVERY_FIXED,
    }.get(rtype, NotificationType.VENDOR_UNCONFIRMED)
    notify_users(
        db,
        store_users(db, order.store_id) + hq_users(db),
        notification_type=notify_type,
        title=f"{RESPONSE_TYPE_LABELS[rtype]} {order.order_no} / {item.product_name}",
        body=(
            f"発注数量 {item.quantity} に対し 納品可能 {deliverable if deliverable is not None else '-'}。"
            f"{payload.reason or payload.shortage_reason or ''}"
        ),
        dedup_key=f"vendor_response:{response.id}",
        order_id=order.id,
        order_item_id=item.id,
    )

    db.commit()
    db.refresh(response)
    return _response_out(response, user.name)


@router.get("/responses", response_model=list[VendorResponseOut])
def list_responses(
    order_id: int | None = None,
    order_item_id: int | None = None,
    latest_only: bool = False,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    """回答履歴。ベンダーユーザーは自社分のみ。"""
    q = db.query(VendorResponse).join(Order, Order.id == VendorResponse.order_id).filter(
        Order.deleted_at.is_(None)
    )
    if scope.vendor_id is not None:
        q = q.filter(VendorResponse.vendor_id == scope.vendor_id)
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if order_id:
        q = q.filter(VendorResponse.order_id == order_id)
    if order_item_id:
        q = q.filter(VendorResponse.order_item_id == order_item_id)
    if latest_only:
        q = q.filter(VendorResponse.is_latest.is_(True))

    rows = q.order_by(VendorResponse.responded_at.desc()).limit(limit).all()
    names = {
        u.id: u.name
        for u in db.query(User).filter(User.id.in_({r.responder_id for r in rows})).all()
    } if rows else {}
    return [_response_out(r, names.get(r.responder_id)) for r in rows]


# --------------------------------------------------------------------------
# 代替商品の本部承認
# --------------------------------------------------------------------------
@router.post("/responses/{response_id}/substitute-decision", response_model=VendorResponseOut)
def decide_substitute(
    response_id: int,
    payload: SubstituteDecision,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    """代替商品は本部承認後に確定する。"""
    response = db.query(VendorResponse).filter(VendorResponse.id == response_id).first()
    if response is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "回答が見つかりません")
    if response.response_type != str(ResponseType.SUBSTITUTE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "代替提案ではありません")
    if response.sub_approved_at or response.sub_rejected_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "既に判定済みです")

    order = get_order_for_user(db, response.order_id, user)
    item = db.query(OrderItem).filter(OrderItem.id == response.order_item_id).first()

    now = utcnow()
    if payload.approve:
        response.sub_approved_by = user.id
        response.sub_approved_at = now
        if item is not None:
            item.confirmed_quantity = (response.deliverable_qty or 0) + (
                response.sub_deliverable_qty or 0
            )
            item.note = ((item.note or "") + f"\n代替承認: {response.sub_product_name}").strip()
            db.add(item)
            set_item_status(db, order, item, str(OrderStatus.PARTIAL if response.shortage_qty else OrderStatus.DELIVERED),
                            user, note=f"代替商品承認: {response.sub_product_name}")
        action_label = "代替提案を承認しました"
    else:
        response.sub_rejected_by = user.id
        response.sub_rejected_at = now
        if item is not None:
            set_item_status(db, order, item, str(OrderStatus.SHORTAGE), user,
                            note=f"代替商品却下: {payload.comment or ''}")
        action_label = "代替提案を却下しました"

    db.add(response)
    recalc_order_status(db, order, user)
    log_action(db, user, AuditAction.VENDOR_SUBSTITUTE, target_type="vendor_response",
               target_id=response.id,
               detail={"判定": "承認" if payload.approve else "却下", "コメント": payload.comment},
               request=request)
    notify_users(
        db,
        store_users(db, order.store_id),
        notification_type=NotificationType.SUBSTITUTE,
        title=f"{action_label} {order.order_no}",
        body=f"代替商品: {response.sub_product_name}",
        dedup_key=f"substitute_decision:{response.id}",
        order_id=order.id,
    )
    db.commit()
    db.refresh(response)
    return _response_out(response)


# --------------------------------------------------------------------------
# ベンダー向け集計
# --------------------------------------------------------------------------
@router.get("/summary/by-product")
def summary_by_product(
    delivery_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    """商品別の合計数量と店舗別内訳。ベンダーは自社分のみ。"""
    q = (
        db.query(OrderItem, Order, Store)
        .join(Order, Order.id == OrderItem.order_id)
        .join(Store, Store.id == Order.store_id)
        .filter(
            Order.deleted_at.is_(None),
            OrderItem.deleted_at.is_(None),
            Order.status.in_([str(s) for s in VENDOR_VISIBLE_STATUSES]),
        )
    )
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if delivery_date:
        q = q.filter(Order.delivery_date == delivery_date)
    if date_from:
        q = q.filter(Order.delivery_date >= date_from)
    if date_to:
        q = q.filter(Order.delivery_date <= date_to)

    agg: dict[int, dict] = {}
    for item, order, store in q.all():
        row = agg.setdefault(
            item.product_id,
            {
                "product_id": item.product_id,
                "jan_code": item.jan_code,
                "product_name": item.product_name,
                "spec": item.spec,
                "order_unit": item.order_unit,
                "case_qty": item.case_qty,
                "total_quantity": 0,
                "total_case": 0,
                "total_loose": 0,
                "store_breakdown": {},
            },
        )
        row["total_quantity"] += item.quantity
        row["total_case"] += item.qty_case
        row["total_loose"] += item.qty_loose
        sb = row["store_breakdown"].setdefault(
            store.id,
            {"store_id": store.id, "store_name": store.name, "quantity": 0, "qty_case": 0,
             "qty_loose": 0, "status": item.status,
             "status_label": ORDER_STATUS_LABELS.get(OrderStatus(item.status), item.status)},
        )
        sb["quantity"] += item.quantity
        sb["qty_case"] += item.qty_case
        sb["qty_loose"] += item.qty_loose

    result = []
    for row in agg.values():
        row["store_breakdown"] = sorted(row["store_breakdown"].values(), key=lambda x: x["store_name"])
        result.append(row)
    return sorted(result, key=lambda r: r["product_name"])


@router.get("/summary/by-delivery-date")
def summary_by_delivery_date(
    date_from: date | None = None,
    date_to: date | None = None,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    """納品日別の件数・数量・未回答件数。"""
    q = scoped_order_query(db, scope)
    if date_from:
        q = q.filter(Order.delivery_date >= date_from)
    if date_to:
        q = q.filter(Order.delivery_date <= date_to)

    result: dict[date, dict] = {}
    for order in q.options(joinedload(Order.items)).all():
        row = result.setdefault(
            order.delivery_date,
            {
                "delivery_date": order.delivery_date,
                "order_count": 0,
                "item_count": 0,
                "total_quantity": 0,
                "pending_count": 0,
                "shortage_count": 0,
                "partial_count": 0,
            },
        )
        row["order_count"] += 1
        for item in order.items:
            if item.deleted_at is not None:
                continue
            row["item_count"] += 1
            row["total_quantity"] += item.quantity
            if item.status == str(OrderStatus.VENDOR_PENDING):
                row["pending_count"] += 1
            elif item.status == str(OrderStatus.SHORTAGE):
                row["shortage_count"] += 1
            elif item.status == str(OrderStatus.PARTIAL):
                row["partial_count"] += 1
    return sorted(result.values(), key=lambda r: r["delivery_date"])


@router.get("/summary/by-store")
def summary_by_store(
    delivery_date: date | None = None,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    """店舗別の数量合計。ベンダーは自社分のみ。"""
    q = (
        db.query(
            Store.id,
            Store.name,
            func.count(func.distinct(Order.id)),
            func.coalesce(func.sum(OrderItem.quantity), 0),
        )
        .join(Order, Order.store_id == Store.id)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            Order.deleted_at.is_(None),
            OrderItem.deleted_at.is_(None),
            Order.status.in_([str(s) for s in VENDOR_VISIBLE_STATUSES]),
        )
    )
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if delivery_date:
        q = q.filter(Order.delivery_date == delivery_date)

    return [
        {"store_id": sid, "store_name": name, "order_count": oc, "total_quantity": int(qty)}
        for sid, name, oc, qty in q.group_by(Store.id, Store.name).order_by(Store.name).all()
    ]
