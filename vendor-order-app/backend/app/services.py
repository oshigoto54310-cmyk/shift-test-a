"""発注まわりの共通ロジック。

ルータから重複ロジックを追い出し、権限フィルタと履歴保存を必ず通るようにする。
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query, Session, joinedload, make_transient

from .config import settings
from .constants import (
    ORDER_STATUS_LABELS,
    RESPONSE_TYPE_LABELS,
    CROSS_TENANT_ROLES,
    OrderStatus,
    RoleCode,
    VENDOR_VISIBLE_STATUSES,
)
from .deadlines import resolve_deadline, resolve_order_deadline
from .deps import AccessScope, forbidden
from .models import (
    IdempotencyKey,
    Order,
    OrderHistory,
    OrderItem,
    OrderStatusHistory,
    Product,
    User,
    VendorResponse,
    utcnow,
)
from .schemas import OrderItemOut, OrderOut, OrderValidationWarning

# 納品日として受け付ける上限（今日からの日数）。年の打ち間違いを弾くため。
MAX_DELIVERY_DAYS_AHEAD = 365


# --------------------------------------------------------------------------
# 二重送信防止
# --------------------------------------------------------------------------
def consume_idempotency_token(
    db: Session, user: User, token: str | None, endpoint: str
) -> None:
    """同じトークンが2回来たら 409 を返す。トークン未指定なら素通し。

    SAVEPOINT を使うため、衝突しても呼び出し側のトランザクション全体は巻き戻らない。
    """
    if not token:
        return
    savepoint = db.begin_nested()
    try:
        db.add(IdempotencyKey(token=token[:80], user_id=user.id, endpoint=endpoint))
        db.flush()
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "この操作は既に受け付けています（二重送信）"
        )


# --------------------------------------------------------------------------
# 競合制御
# --------------------------------------------------------------------------
def claim_status_transition(
    db: Session,
    model,
    row_id: int,
    *,
    from_statuses: list[str],
    to_status: str,
    extra: dict | None = None,
) -> bool:
    """条件付きUPDATEで状態遷移を「1人だけ」に確定させる。

    「読んで判定してから書く」方式だと、同時に複数のリクエストが同じ判定を通過し、
    全員が成功してしまう（発注の多重確定・変更申請の多重承認）。
    UPDATE ... WHERE status IN (...) の更新行数で勝者を決めることで、
    データベースの行ロックに判定を任せる。

    戻り値: True = 自分が遷移させた / False = 既に他の誰かが遷移させた
    """
    values = {"status": to_status}
    if extra:
        values.update(extra)
    updated = (
        db.query(model)
        .filter(model.id == row_id, model.status.in_(from_statuses))
        .update(values, synchronize_session=False)
    )
    return bool(updated)


def bump_version(db: Session, order: Order) -> None:
    """発注ヘッダの version を進める（楽観ロック用）。"""
    db.query(Order).filter(Order.id == order.id).update(
        {"version": Order.version + 1}, synchronize_session=False
    )


def claim_order_version(db: Session, order: Order, expected: int) -> None:
    """楽観ロック。version が一致する場合だけ +1 して更新権を取得する。

    「読んで比較してから書く」方式では、2つのリクエストが同じ version を読んだ場合に
    両方が判定を通過して後勝ちの上書きが起きる。
    UPDATE ... WHERE version = :expected の更新行数で勝者を決めることで、
    データベースの行ロックに判定を任せる。
    この UPDATE は以降の処理が終わるまで行ロックを保持するため、
    同一発注に対する更新は直列化される。
    """
    updated = (
        db.query(Order)
        .filter(Order.id == order.id, Order.version == expected)
        .update({"version": Order.version + 1}, synchronize_session=False)
    )
    if not updated:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "他の担当者がこの発注を更新しました。"
            "最新の内容を読み込んでから、もう一度やり直してください。",
        )
    order.version = expected + 1


# --------------------------------------------------------------------------
# 数量計算
# --------------------------------------------------------------------------
def compute_quantity(case_qty: int, qty_case: int, qty_loose: int) -> int:
    """ケース数・バラ数から合計（バラ換算）数量を求める。"""
    return max(int(case_qty or 1), 1) * int(qty_case or 0) + int(qty_loose or 0)


def new_order_no(db: Session, store_code: str, delivery_date: date) -> str:
    prefix = f"{delivery_date:%Y%m%d}-{store_code}"
    count = db.query(func.count(Order.id)).filter(Order.order_no.like(f"{prefix}-%")).scalar() or 0
    for n in range(count + 1, count + 500):
        candidate = f"{prefix}-{n:03d}"
        if not db.query(Order.id).filter(Order.order_no == candidate).first():
            return candidate
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "発注番号を採番できませんでした")


def insert_order_with_unique_no(
    db: Session, order: Order, store_code: str, attempts: int = 8
) -> Order:
    """発注番号を採番して INSERT する。衝突したら採番からやり直す。

    採番は「既存件数を数えて次の番号を決める」方式のため、同時登録が重なると
    同じ番号を掴む。UNIQUE 制約で弾かれるのを SAVEPOINT で受け止め、
    番号を採り直して再試行する（そのまま流すと 500 になる）。
    """
    last_error: IntegrityError | None = None
    for _ in range(attempts):
        order.order_no = new_order_no(db, store_code, order.delivery_date)
        savepoint = db.begin_nested()
        try:
            db.add(order)
            db.flush()
            savepoint.commit()
            return order
        except IntegrityError as exc:
            savepoint.rollback()
            last_error = exc
            # SAVEPOINT を巻き戻すとインスタンスはセッションから外れる。
            # 再び add できるよう transient に戻してから採番し直す。
            make_transient(order)
            order.id = None
    raise HTTPException(
        status.HTTP_409_CONFLICT,
        "発注番号の採番が混み合っています。少し時間をおいて再度お試しください。",
    ) from last_error


# --------------------------------------------------------------------------
# 権限スコープ付きクエリ
# --------------------------------------------------------------------------
def scoped_order_query(db: Session, scope: AccessScope) -> Query:
    """必ずこの関数経由で発注を検索する。ここで店舗／ベンダー分離を強制する。"""
    q = (
        db.query(Order)
        .options(joinedload(Order.store), joinedload(Order.vendor))
        .filter(Order.deleted_at.is_(None))
    )
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if scope.is_vendor_user:
        # ベンダーには確定前（下書き・発注予定）の発注は見せない
        q = q.filter(Order.status.in_([str(s) for s in VENDOR_VISIBLE_STATUSES]))
    return q


def get_order_for_user(db: Session, order_id: int, user: User) -> Order:
    """1件取得。存在＋権限を確認する。権限外は 403。"""
    order = (
        db.query(Order)
        .options(
            joinedload(Order.store),
            joinedload(Order.vendor),
            joinedload(Order.items).joinedload(OrderItem.product),
        )
        .filter(Order.id == order_id, Order.deleted_at.is_(None))
        .first()
    )
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "発注が見つかりません")

    role = user.role.code
    if role in {str(r) for r in CROSS_TENANT_ROLES}:
        return order
    if role == RoleCode.STORE:
        if user.store_id != order.store_id:
            raise forbidden("他店舗の発注にはアクセスできません")
        return order
    if role == RoleCode.VENDOR:
        if user.vendor_id != order.vendor_id:
            raise forbidden("他ベンダーの発注にはアクセスできません")
        if order.status not in {str(s) for s in VENDOR_VISIBLE_STATUSES}:
            # 未確定の発注はベンダーには存在しないものとして扱う
            raise forbidden("この発注はまだ確定していません")
        return order
    raise forbidden()


def get_item_for_user(db: Session, item_id: int, user: User) -> tuple[Order, OrderItem]:
    item = (
        db.query(OrderItem)
        .filter(OrderItem.id == item_id, OrderItem.deleted_at.is_(None))
        .first()
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "発注明細が見つかりません")
    order = get_order_for_user(db, item.order_id, user)
    return order, item


# --------------------------------------------------------------------------
# 締め判定
# --------------------------------------------------------------------------
def is_after_deadline(order: Order) -> bool:
    if order.deadline_at is None:
        return False
    return utcnow() > order.deadline_at


def assert_before_deadline(order: Order) -> None:
    if is_after_deadline(order):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "締め時間を過ぎているため直接変更できません。変更申請を作成してください。",
        )


# --------------------------------------------------------------------------
# 履歴保存
# --------------------------------------------------------------------------
def record_status(
    db: Session,
    order: Order,
    status_before: str | None,
    status_after: str,
    user: User | None,
    *,
    item: OrderItem | None = None,
    note: str | None = None,
) -> None:
    if status_before == status_after:
        return
    db.add(
        OrderStatusHistory(
            order_id=order.id,
            order_item_id=item.id if item else None,
            status_before=status_before,
            status_after=status_after,
            changed_by=user.id if user else None,
            note=note,
        )
    )


def record_quantity_change(
    db: Session,
    order: Order,
    item: OrderItem,
    *,
    before: tuple[int, int, int],
    after: tuple[int, int, int],
    user: User | None,
    reason: str | None = None,
    after_deadline: bool = False,
    change_request_id: int | None = None,
    requester_id: int | None = None,
    approver_id: int | None = None,
    approved_at=None,
    reject_reason: str | None = None,
) -> OrderHistory:
    """数量変更履歴を1行残す。数量が動いたら必ず呼ぶこと。"""
    history = OrderHistory(
        order_id=order.id,
        order_item_id=item.id,
        case_before=before[0],
        loose_before=before[1],
        qty_before=before[2],
        case_after=after[0],
        loose_after=after[1],
        qty_after=after[2],
        reason=reason,
        changed_by=user.id if user else None,
        is_after_deadline=after_deadline,
        change_request_id=change_request_id,
        requester_id=requester_id,
        approver_id=approver_id,
        approved_at=approved_at,
        reject_reason=reject_reason,
    )
    db.add(history)
    return history


def set_item_status(
    db: Session, order: Order, item: OrderItem, new_status: str, user: User | None, note: str | None = None
) -> None:
    before = item.status
    if before == new_status:
        return
    item.status = new_status
    db.add(item)
    record_status(db, order, before, new_status, user, item=item, note=note)


def set_order_status(
    db: Session, order: Order, new_status: str, user: User | None, note: str | None = None
) -> None:
    before = order.status
    if before == new_status:
        return
    order.status = new_status
    db.add(order)
    record_status(db, order, before, new_status, user, note=note)


def recalc_order_status(db: Session, order: Order, user: User | None) -> None:
    """明細のステータスから発注ヘッダのステータスを導出する。

    優先度の高い状態（欠品・代替提案・一部納品・変更申請中）が1件でもあればそれを採用する。
    """
    statuses = {i.status for i in order.items if i.deleted_at is None}
    if not statuses:
        return
    if statuses == {str(OrderStatus.CANCELLED)}:
        set_order_status(db, order, str(OrderStatus.CANCELLED), user)
        return

    live = statuses - {str(OrderStatus.CANCELLED)}
    for candidate in (
        OrderStatus.CHANGE_REQUESTED,
        OrderStatus.SHORTAGE,
        OrderStatus.SUBSTITUTE,
        OrderStatus.PARTIAL,
    ):
        if str(candidate) in live:
            set_order_status(db, order, str(candidate), user)
            return
    if live == {str(OrderStatus.DELIVERED)}:
        set_order_status(db, order, str(OrderStatus.DELIVERED), user)
        return
    if live <= {str(OrderStatus.VENDOR_ACK), str(OrderStatus.DELIVERED)}:
        set_order_status(db, order, str(OrderStatus.VENDOR_ACK), user)
        return
    if str(OrderStatus.VENDOR_PENDING) in live:
        set_order_status(db, order, str(OrderStatus.VENDOR_PENDING), user)
        return
    if str(OrderStatus.CHANGE_APPROVED) in live:
        set_order_status(db, order, str(OrderStatus.CHANGE_APPROVED), user)


# --------------------------------------------------------------------------
# 入力チェック
# --------------------------------------------------------------------------
def validate_order_items(
    db: Session,
    *,
    store_id: int,
    delivery_date: date,
    items: list,
    exclude_order_id: int | None = None,
) -> list[OrderValidationWarning]:
    """発注入力のチェック。level=ERROR が1件でもあれば登録させない。"""
    warnings: list[OrderValidationWarning] = []
    today = date.today()

    if delivery_date < today:
        warnings.append(
            OrderValidationWarning(
                code="PAST_DELIVERY_DATE",
                message=f"納品日 {delivery_date:%Y/%m/%d} は過去日です。登録できません。",
                level="ERROR",
            )
        )
    # 桁誤り・年の打ち間違いを弾く。1年より先の納品日は業務上ありえない。
    if delivery_date > today + timedelta(days=MAX_DELIVERY_DAYS_AHEAD):
        warnings.append(
            OrderValidationWarning(
                code="DELIVERY_DATE_TOO_FAR",
                message=(
                    f"納品日 {delivery_date:%Y/%m/%d} が遠すぎます"
                    f"（{MAX_DELIVERY_DAYS_AHEAD}日先まで）。日付を確認してください。"
                ),
                level="ERROR",
            )
        )

    for line in items:
        product = (
            db.query(Product)
            .filter(Product.id == line.product_id, Product.deleted_at.is_(None))
            .first()
        )
        if product is None:
            warnings.append(
                OrderValidationWarning(
                    code="PRODUCT_NOT_FOUND",
                    message=f"商品ID {line.product_id} が見つかりません。",
                    product_id=line.product_id,
                    level="ERROR",
                )
            )
            continue

        name = product.name
        if not product.is_active:
            warnings.append(
                OrderValidationWarning(
                    code="PRODUCT_INACTIVE",
                    message=f"{name} は無効な商品です。",
                    product_id=product.id,
                    level="ERROR",
                )
            )
        if product.valid_from and delivery_date < product.valid_from:
            warnings.append(
                OrderValidationWarning(
                    code="PRODUCT_NOT_YET_VALID",
                    message=f"{name} は {product.valid_from:%Y/%m/%d} からの取扱です。",
                    product_id=product.id,
                )
            )
        if product.valid_to and delivery_date > product.valid_to:
            warnings.append(
                OrderValidationWarning(
                    code="PRODUCT_EXPIRED",
                    message=f"{name} は {product.valid_to:%Y/%m/%d} で取扱終了です。",
                    product_id=product.id,
                )
            )

        quantity = compute_quantity(product.case_qty, line.qty_case, line.qty_loose)

        if quantity == 0:
            warnings.append(
                OrderValidationWarning(
                    code="ZERO_QUANTITY",
                    message=f"{name} の数量が0です。",
                    product_id=product.id,
                )
            )
        if quantity >= settings.abnormal_qty_threshold:
            warnings.append(
                OrderValidationWarning(
                    code="ABNORMAL_QUANTITY",
                    message=f"{name} の数量 {quantity} は通常より大きい値です。確認してください。",
                    product_id=product.id,
                )
            )
        if product.cost is None:
            warnings.append(
                OrderValidationWarning(
                    code="COST_MISSING",
                    message=f"{name} は原価が未登録です。",
                    product_id=product.id,
                )
            )
        if line.qty_loose and not product.allow_loose:
            warnings.append(
                OrderValidationWarning(
                    code="LOOSE_NOT_ALLOWED",
                    message=f"{name} はバラ発注できません。ケース数で入力してください。",
                    product_id=product.id,
                    level="ERROR",
                )
            )
        if product.case_qty and line.qty_loose >= product.case_qty and product.case_qty > 1:
            warnings.append(
                OrderValidationWarning(
                    code="CASE_QTY_MISMATCH",
                    message=(
                        f"{name} のバラ数 {line.qty_loose} がケース入数 {product.case_qty} 以上です。"
                        "ケース数に繰り上げてください。"
                    ),
                    product_id=product.id,
                )
            )
        if product.order_unit == "CASE" and line.qty_loose:
            warnings.append(
                OrderValidationWarning(
                    code="ORDER_UNIT_MISMATCH",
                    message=f"{name} の発注単位はケースです。バラ数は指定できません。",
                    product_id=product.id,
                )
            )
        if product.order_unit == "PIECE" and line.qty_case:
            warnings.append(
                OrderValidationWarning(
                    code="ORDER_UNIT_MISMATCH",
                    message=f"{name} の発注単位はバラです。ケース数は指定できません。",
                    product_id=product.id,
                )
            )

        # 同一店舗・同一商品・同一納品日の重複発注
        dup_q = (
            db.query(OrderItem.id)
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                Order.store_id == store_id,
                Order.delivery_date == delivery_date,
                Order.deleted_at.is_(None),
                Order.status != str(OrderStatus.CANCELLED),
                OrderItem.product_id == product.id,
                OrderItem.deleted_at.is_(None),
            )
        )
        if exclude_order_id is not None:
            dup_q = dup_q.filter(Order.id != exclude_order_id)
        if dup_q.first():
            warnings.append(
                OrderValidationWarning(
                    code="DUPLICATE_ORDER",
                    message=f"{name} は同じ納品日に既に発注があります。重複していないか確認してください。",
                    product_id=product.id,
                )
            )

        # 締め時間超過
        dl = resolve_deadline(
            db, delivery_date=delivery_date, vendor_id=product.vendor_id, product_id=product.id
        )
        if utcnow() > dl.final_deadline_at:
            warnings.append(
                OrderValidationWarning(
                    code="DEADLINE_PASSED",
                    message=f"{name} は締め時間を過ぎています。締め後の登録は変更申請が必要です。",
                    product_id=product.id,
                )
            )

    return warnings


def has_blocking(warnings: list[OrderValidationWarning]) -> bool:
    return any(w.level == "ERROR" for w in warnings)


# --------------------------------------------------------------------------
# 出力整形
# --------------------------------------------------------------------------
def latest_response_map(db: Session, item_ids: list[int]) -> dict[int, VendorResponse]:
    if not item_ids:
        return {}
    rows = (
        db.query(VendorResponse)
        .filter(VendorResponse.order_item_id.in_(item_ids), VendorResponse.is_latest.is_(True))
        .all()
    )
    return {r.order_item_id: r for r in rows}


def item_to_out(item: OrderItem, response: VendorResponse | None = None) -> OrderItemOut:
    out = OrderItemOut.model_validate(item)
    out.status_label = ORDER_STATUS_LABELS.get(OrderStatus(item.status), item.status)
    out.cost = float(item.cost) if item.cost is not None else None
    if response is not None:
        out.latest_response = {
            "id": response.id,
            "response_type": response.response_type,
            "response_label": RESPONSE_TYPE_LABELS.get(
                response.response_type, response.response_type
            ),
            "deliverable_qty": response.deliverable_qty,
            "shortage_qty": response.shortage_qty,
            "reason": response.reason,
            "shortage_reason": response.shortage_reason,
            "next_available_date": response.next_available_date,
            "has_substitute": response.has_substitute,
            "sub_product_name": response.sub_product_name,
            "sub_deliverable_qty": response.sub_deliverable_qty,
            "sub_approved_at": response.sub_approved_at,
            "sub_rejected_at": response.sub_rejected_at,
            "comment": response.comment,
            "responded_at": response.responded_at,
        }
    return out


def order_to_out(
    order: Order, *, include_items: bool = True, responses: dict[int, VendorResponse] | None = None
) -> OrderOut:
    out = OrderOut.model_validate(order)
    out.store_name = order.store.name if order.store else None
    out.vendor_name = order.vendor.name if order.vendor else None
    out.status_label = ORDER_STATUS_LABELS.get(OrderStatus(order.status), order.status)
    out.is_after_deadline = is_after_deadline(order)
    live_items = [i for i in order.items if i.deleted_at is None]
    out.total_quantity = sum(i.quantity for i in live_items)
    out.item_count = len(live_items)
    if include_items:
        responses = responses or {}
        out.items = [item_to_out(i, responses.get(i.id)) for i in live_items]
    else:
        out.items = []
    return out


def apply_deadlines(db: Session, order: Order, product_ids: list[int]) -> None:
    dl = resolve_order_deadline(
        db, delivery_date=order.delivery_date, vendor_id=order.vendor_id, product_ids=product_ids
    )
    order.rough_deadline_at = dl.rough_deadline_at
    order.deadline_at = dl.final_deadline_at
    order.reply_deadline_at = dl.reply_deadline_at
