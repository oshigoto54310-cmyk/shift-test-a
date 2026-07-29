"""発注API。

重要な不変条件:
- 発注の検索は必ず scoped_order_query / get_order_for_user を通す。
- 数量が動いたら必ず order_histories に1行残す。
- 締め後は数量を直接書き換えない（変更申請に回す）。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..constants import (
    EDITABLE_STATUSES,
    AuditAction,
    NotificationType,
    OrderStatus,
    RoleCode,
)
from ..database import get_db
from ..deps import AccessScope, build_scope, forbidden, get_current_user, scope_dependency
from ..models import Order, OrderItem, OrderStatusHistory, Product, Store, User, Vendor, utcnow
from ..notify import notify_users, order_stakeholders, store_users, vendor_users
from ..schemas import (
    OrderCancelRequest,
    OrderConfirmRequest,
    OrderCreate,
    OrderOut,
    OrderUpdate,
    OrderValidateRequest,
    OrderValidateResponse,
)
from ..services import (
    apply_deadlines,
    assert_before_deadline,
    compute_quantity,
    consume_idempotency_token,
    get_order_for_user,
    has_blocking,
    is_after_deadline,
    latest_response_map,
    new_order_no,
    order_to_out,
    record_quantity_change,
    scoped_order_query,
    set_item_status,
    set_order_status,
    validate_order_items,
)

router = APIRouter(prefix="/api/orders", tags=["発注"])


def _resolve_target_store(user: User, requested: int | None) -> int:
    """発注登録先の店舗を決める。店舗ユーザーは自店舗に強制する。"""
    if user.role.code == RoleCode.STORE:
        if requested is not None and requested != user.store_id:
            raise forbidden("他店舗の発注は登録できません")
        if user.store_id is None:
            raise forbidden("店舗が割り当てられていません")
        return user.store_id
    if user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーは発注を登録できません")
    if requested is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "店舗を指定してください")
    return requested


# --------------------------------------------------------------------------
# 一覧・詳細
# --------------------------------------------------------------------------
@router.get("", response_model=list[OrderOut])
def list_orders(
    delivery_date: date | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    order_status: str | None = Query(default=None, alias="status"),
    q: str | None = None,
    include_items: bool = False,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    query = scoped_order_query(db, scope)
    if delivery_date:
        query = query.filter(Order.delivery_date == delivery_date)
    if date_from:
        query = query.filter(Order.delivery_date >= date_from)
    if date_to:
        query = query.filter(Order.delivery_date <= date_to)
    if order_status:
        query = query.filter(Order.status.in_([s.strip() for s in order_status.split(",")]))
    if q:
        query = query.filter(Order.order_no.like(f"%{q.strip()}%"))

    if include_items:
        query = query.options(joinedload(Order.items))

    rows = (
        query.order_by(Order.delivery_date.desc(), Order.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    responses = {}
    if include_items:
        item_ids = [i.id for o in rows for i in o.items if i.deleted_at is None]
        responses = latest_response_map(db, item_ids)

    return [order_to_out(o, include_items=include_items, responses=responses) for o in rows]


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    order = get_order_for_user(db, order_id, user)
    responses = latest_response_map(db, [i.id for i in order.items if i.deleted_at is None])
    return order_to_out(order, responses=responses)


@router.get("/{order_id}/editable")
def order_editable(
    order_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """締め前かどうかと、直接編集できるかをフロントに返す。"""
    order = get_order_for_user(db, order_id, user)
    after = is_after_deadline(order)
    can_edit = (
        not after
        and order.status in {str(s) for s in EDITABLE_STATUSES}
        and user.role.code in {RoleCode.ADMIN, RoleCode.HQ, RoleCode.STORE}
    )
    return {
        "is_after_deadline": after,
        "can_edit_directly": can_edit,
        "deadline_at": order.deadline_at,
        "reply_deadline_at": order.reply_deadline_at,
        "requires_change_request": after,
    }


# --------------------------------------------------------------------------
# 入力チェック（登録前の事前確認）
# --------------------------------------------------------------------------
@router.post("/validate", response_model=OrderValidateResponse)
def validate_order(
    payload: OrderValidateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    store_id = _resolve_target_store(user, payload.store_id)
    warnings = validate_order_items(
        db, store_id=store_id, delivery_date=payload.delivery_date, items=payload.items
    )
    return OrderValidateResponse(warnings=warnings, blocking=has_blocking(warnings))


# --------------------------------------------------------------------------
# 登録
# --------------------------------------------------------------------------
@router.post("", response_model=list[OrderOut], status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """発注を登録する。

    商品の担当ベンダーに応じて自動的にベンダー別の発注へ振り分けるため、
    戻り値は複数件になりうる。
    """
    store_id = _resolve_target_store(user, payload.store_id)
    consume_idempotency_token(db, user, payload.client_token, "create_order")

    warnings = validate_order_items(
        db, store_id=store_id, delivery_date=payload.delivery_date, items=payload.items
    )
    if has_blocking(warnings):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"message": "入力内容にエラーがあります", "warnings": [w.model_dump() for w in warnings]},
        )

    store = db.query(Store).filter(Store.id == store_id, Store.deleted_at.is_(None)).first()
    if not store:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "店舗が見つかりません")

    products = {
        p.id: p
        for p in db.query(Product)
        .filter(Product.id.in_([i.product_id for i in payload.items]), Product.deleted_at.is_(None))
        .all()
    }

    # 商品の担当ベンダーごとに発注を分割する（＝ベンダー自動振り分け）
    by_vendor: dict[int, list] = defaultdict(list)
    for line in payload.items:
        product = products.get(line.product_id)
        if product is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "商品が見つかりません")
        if payload.vendor_id is not None and product.vendor_id != payload.vendor_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{product.name} は指定されたベンダーの商品ではありません",
            )
        by_vendor[product.vendor_id].append((line, product))

    created_orders: list[Order] = []
    initial_status = str(OrderStatus.CONFIRMED if payload.confirm else OrderStatus.DRAFT)

    for vendor_id, lines in by_vendor.items():
        vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.deleted_at.is_(None)).first()
        if not vendor:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "担当ベンダーが見つかりません")

        order = Order(
            order_no=new_order_no(db, store.code, payload.delivery_date),
            store_id=store_id,
            vendor_id=vendor_id,
            delivery_date=payload.delivery_date,
            status=initial_status,
            note=payload.note,
            created_by=user.id,
            updated_by=user.id,
        )
        apply_deadlines(db, order, [p.id for _, p in lines])
        if payload.confirm:
            order.confirmed_at = utcnow()
            order.confirmed_by = user.id
        db.add(order)
        db.flush()

        item_status = str(OrderStatus.VENDOR_PENDING if payload.confirm else OrderStatus.DRAFT)
        for line, product in lines:
            quantity = compute_quantity(product.case_qty, line.qty_case, line.qty_loose)
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                jan_code=product.jan_code,
                product_name=product.name,
                spec=product.spec,
                order_unit=product.order_unit,
                case_qty=product.case_qty,
                cost=product.cost,
                qty_case=line.qty_case,
                qty_loose=line.qty_loose,
                quantity=quantity,
                status=item_status,
                note=line.note,
                created_by=user.id,
                updated_by=user.id,
            )
            db.add(item)
            db.flush()
            record_quantity_change(
                db,
                order,
                item,
                before=(0, 0, 0),
                after=(item.qty_case, item.qty_loose, item.quantity),
                user=user,
                reason="新規登録",
                after_deadline=False,
            )
            db.add(
                # 明細の初期ステータスも履歴に残す
                OrderStatusHistory(
                    order_id=order.id,
                    order_item_id=item.id,
                    status_before=None,
                    status_after=item_status,
                    changed_by=user.id,
                    note="発注登録",
                )
            )

        db.add(
            OrderStatusHistory(
                order_id=order.id,
                status_before=None,
                status_after=initial_status,
                changed_by=user.id,
                note="発注登録",
            )
        )
        created_orders.append(order)

        log_action(
            db, user, AuditAction.ORDER_CREATE, target_type="order", target_id=order.id,
            detail={"order_no": order.order_no, "vendor_id": vendor_id, "確定": payload.confirm},
            request=request,
        )

        recipients = order_stakeholders(db, order, include_vendor=payload.confirm)
        notify_users(
            db,
            recipients,
            notification_type=NotificationType.ORDER_CREATED,
            title=f"新規発注 {order.order_no}（{store.name} / {vendor.name}）",
            body=f"納品日 {order.delivery_date:%Y/%m/%d} の発注が登録されました。",
            dedup_key=f"order_created:{order.id}",
            order_id=order.id,
        )
        if payload.confirm:
            log_action(db, user, AuditAction.ORDER_CONFIRM, target_type="order", target_id=order.id,
                       detail={"order_no": order.order_no}, request=request)
            notify_users(
                db,
                vendor_users(db, vendor_id),
                notification_type=NotificationType.ORDER_CONFIRMED,
                title=f"発注確定 {order.order_no}",
                body=f"{store.name} から納品日 {order.delivery_date:%Y/%m/%d} の発注が確定しました。",
                dedup_key=f"order_confirmed:{order.id}",
                order_id=order.id,
            )

    db.commit()
    for o in created_orders:
        db.refresh(o)
    return [order_to_out(o) for o in created_orders]


# --------------------------------------------------------------------------
# 更新（締め前のみ）
# --------------------------------------------------------------------------
@router.put("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    payload: OrderUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = get_order_for_user(db, order_id, user)

    if user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーは発注内容を変更できません")
    if order.status in {str(OrderStatus.CANCELLED)}:
        raise HTTPException(status.HTTP_409_CONFLICT, "取消済みの発注は変更できません")

    # 締め後は直接上書きさせない
    assert_before_deadline(order)
    consume_idempotency_token(db, user, payload.client_token, f"update_order:{order_id}")

    existing = {i.id: i for i in order.items if i.deleted_at is None}
    seen_ids: set[int] = set()
    changed = False

    for line in payload.items:
        product = (
            db.query(Product)
            .filter(Product.id == line.product_id, Product.deleted_at.is_(None))
            .first()
        )
        if product is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "商品が見つかりません")
        if product.vendor_id != order.vendor_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"{product.name} は この発注のベンダーの商品ではありません",
            )
        if line.qty_loose and not product.allow_loose:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"{product.name} はバラ発注できません"
            )

        quantity = compute_quantity(product.case_qty, line.qty_case, line.qty_loose)

        item = existing.get(line.id) if line.id else None
        if item is None:
            # 同じ商品の既存明細があればそれを更新対象にする
            item = next(
                (i for i in existing.values() if i.product_id == product.id and i.id not in seen_ids),
                None,
            )

        if item is None:
            item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                jan_code=product.jan_code,
                product_name=product.name,
                spec=product.spec,
                order_unit=product.order_unit,
                case_qty=product.case_qty,
                cost=product.cost,
                qty_case=line.qty_case,
                qty_loose=line.qty_loose,
                quantity=quantity,
                status=order.status if order.status != str(OrderStatus.DRAFT) else str(OrderStatus.DRAFT),
                note=line.note,
                created_by=user.id,
                updated_by=user.id,
            )
            db.add(item)
            db.flush()
            record_quantity_change(
                db, order, item, before=(0, 0, 0),
                after=(item.qty_case, item.qty_loose, item.quantity),
                user=user, reason=line.reason or "明細追加",
            )
            changed = True
        else:
            seen_ids.add(item.id)
            before = (item.qty_case, item.qty_loose, item.quantity)
            after = (line.qty_case, line.qty_loose, quantity)
            item.note = line.note
            if before != after:
                item.qty_case, item.qty_loose, item.quantity = after
                item.updated_by = user.id
                db.add(item)
                record_quantity_change(
                    db, order, item, before=before, after=after, user=user,
                    reason=line.reason or "締め前修正", after_deadline=False,
                )
                changed = True

    # 送られてこなかった明細は数量0扱いではなく論理削除（履歴は残す）
    for item_id, item in existing.items():
        if item_id in seen_ids:
            continue
        if any(l.id == item_id for l in payload.items):
            continue
        if any(l.product_id == item.product_id for l in payload.items):
            continue
        before = (item.qty_case, item.qty_loose, item.quantity)
        item.deleted_at = utcnow()
        item.deleted_by = user.id
        db.add(item)
        record_quantity_change(
            db, order, item, before=before, after=(0, 0, 0), user=user, reason="明細削除"
        )
        changed = True

    order.note = payload.note if payload.note is not None else order.note
    order.updated_by = user.id
    live_products = [i.product_id for i in order.items if i.deleted_at is None]
    apply_deadlines(db, order, live_products)
    db.add(order)

    log_action(db, user, AuditAction.ORDER_UPDATE, target_type="order", target_id=order.id,
               detail={"order_no": order.order_no, "変更あり": changed}, request=request)

    if changed:
        notify_users(
            db,
            order_stakeholders(db, order, include_vendor=order.status != str(OrderStatus.DRAFT)),
            notification_type=NotificationType.ORDER_QTY_CHANGED,
            title=f"発注数量変更 {order.order_no}",
            body=f"納品日 {order.delivery_date:%Y/%m/%d} の発注数量が変更されました。",
            dedup_key=f"order_changed:{order.id}:{utcnow():%Y%m%d%H%M%S}",
            order_id=order.id,
        )

    db.commit()
    db.refresh(order)
    responses = latest_response_map(db, [i.id for i in order.items if i.deleted_at is None])
    return order_to_out(order, responses=responses)


# --------------------------------------------------------------------------
# 確定・取消
# --------------------------------------------------------------------------
@router.post("/{order_id}/confirm", response_model=OrderOut)
def confirm_order(
    order_id: int,
    payload: OrderConfirmRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = get_order_for_user(db, order_id, user)
    if user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーは発注を確定できません")
    if order.status not in {str(OrderStatus.DRAFT), str(OrderStatus.PLANNED)}:
        raise HTTPException(status.HTTP_409_CONFLICT, "この発注は既に確定または処理済みです")

    consume_idempotency_token(db, user, payload.client_token, f"confirm_order:{order_id}")

    live_items = [i for i in order.items if i.deleted_at is None]
    if not live_items:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "明細がありません")
    if all(i.quantity == 0 for i in live_items):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "数量がすべて0です")

    set_order_status(db, order, str(OrderStatus.CONFIRMED), user, note="発注確定")
    order.confirmed_at = utcnow()
    order.confirmed_by = user.id
    order.updated_by = user.id
    db.add(order)
    for item in live_items:
        set_item_status(db, order, item, str(OrderStatus.VENDOR_PENDING), user, note="発注確定")

    log_action(db, user, AuditAction.ORDER_CONFIRM, target_type="order", target_id=order.id,
               detail={"order_no": order.order_no}, request=request)
    notify_users(
        db,
        vendor_users(db, order.vendor_id) + store_users(db, order.store_id),
        notification_type=NotificationType.ORDER_CONFIRMED,
        title=f"発注確定 {order.order_no}",
        body=f"納品日 {order.delivery_date:%Y/%m/%d} の発注が確定しました。ご確認ください。",
        dedup_key=f"order_confirmed:{order.id}",
        order_id=order.id,
    )
    db.commit()
    db.refresh(order)
    return order_to_out(order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(
    order_id: int,
    payload: OrderCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = get_order_for_user(db, order_id, user)
    if user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーは発注を取消できません")
    if order.status == str(OrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT, "既に取消済みです")
    if is_after_deadline(order) and user.role.code == RoleCode.STORE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "締め後の取消は本部承認が必要です。変更申請から依頼してください。",
        )

    for item in [i for i in order.items if i.deleted_at is None]:
        before = (item.qty_case, item.qty_loose, item.quantity)
        set_item_status(db, order, item, str(OrderStatus.CANCELLED), user, note=payload.reason)
        record_quantity_change(
            db, order, item, before=before, after=(0, 0, 0), user=user,
            reason=f"発注取消: {payload.reason}", after_deadline=is_after_deadline(order),
        )
    set_order_status(db, order, str(OrderStatus.CANCELLED), user, note=payload.reason)
    order.updated_by = user.id
    db.add(order)

    log_action(db, user, AuditAction.ORDER_CANCEL, target_type="order", target_id=order.id,
               detail={"order_no": order.order_no, "理由": payload.reason}, request=request)
    notify_users(
        db,
        order_stakeholders(db, order),
        notification_type=NotificationType.ORDER_QTY_CHANGED,
        title=f"発注取消 {order.order_no}",
        body=f"取消理由: {payload.reason}",
        dedup_key=f"order_cancelled:{order.id}",
        order_id=order.id,
    )
    db.commit()
    db.refresh(order)
    return order_to_out(order)


# --------------------------------------------------------------------------
# 発注補助（前回発注コピー等）
# --------------------------------------------------------------------------
@router.get("/helpers/last-order")
def last_order(
    store_id: int | None = None,
    vendor_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """前回発注の明細を返す（コピー入力用）。"""
    scope = build_scope(user, store_id, vendor_id)
    if scope.is_vendor_user:
        raise forbidden("ベンダーユーザーは利用できません")
    query = scoped_order_query(db, scope).filter(
        Order.status != str(OrderStatus.CANCELLED)
    )
    order = query.order_by(Order.delivery_date.desc(), Order.id.desc()).first()
    if order is None:
        return {"order": None, "items": []}
    items = [
        {
            "product_id": i.product_id,
            "product_name": i.product_name,
            "jan_code": i.jan_code,
            "spec": i.spec,
            "case_qty": i.case_qty,
            "order_unit": i.order_unit,
            "qty_case": i.qty_case,
            "qty_loose": i.qty_loose,
        }
        for i in order.items
        if i.deleted_at is None and i.quantity > 0
    ]
    return {
        "order": {
            "id": order.id,
            "order_no": order.order_no,
            "delivery_date": order.delivery_date,
            "vendor_id": order.vendor_id,
            "vendor_name": order.vendor.name if order.vendor else None,
        },
        "items": items,
    }


@router.get("/helpers/recent-products")
def recent_products(
    store_id: int | None = None,
    limit: int = Query(default=30, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """前回発注商品（直近で発注した商品）を返す。"""
    scope = build_scope(user, store_id, None)
    if scope.is_vendor_user:
        raise forbidden("ベンダーユーザーは利用できません")

    q = (
        db.query(
            OrderItem.product_id,
            func.max(Order.delivery_date).label("last_date"),
            func.count(OrderItem.id).label("times"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.deleted_at.is_(None),
            OrderItem.deleted_at.is_(None),
            Order.status != str(OrderStatus.CANCELLED),
        )
    )
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    rows = (
        q.group_by(OrderItem.product_id)
        .order_by(func.max(Order.delivery_date).desc())
        .limit(limit)
        .all()
    )
    product_ids = [r[0] for r in rows]
    if not product_ids:
        return []
    products = {
        p.id: p
        for p in db.query(Product)
        .options(joinedload(Product.vendor))
        .filter(Product.id.in_(product_ids), Product.deleted_at.is_(None), Product.is_active.is_(True))
        .all()
    }
    result = []
    for pid, last_date, times in rows:
        p = products.get(pid)
        if not p:
            continue
        result.append(
            {
                "product_id": p.id,
                "jan_code": p.jan_code,
                "name": p.name,
                "spec": p.spec,
                "case_qty": p.case_qty,
                "order_unit": p.order_unit,
                "allow_loose": p.allow_loose,
                "vendor_id": p.vendor_id,
                "vendor_name": p.vendor.name if p.vendor else None,
                "last_delivery_date": last_date,
                "order_times": times,
            }
        )
    return result
