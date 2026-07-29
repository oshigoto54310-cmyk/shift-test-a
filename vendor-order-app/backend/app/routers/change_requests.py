"""締め後の変更申請と承認。

締め後は発注数量を直接上書きさせず、必ずこのフローを通す。
- 申請時: 変更理由を必須入力。発注数量はまだ変えない。
- 承認時: 本部／管理者が承認して初めて数量を更新し、変更履歴を残す。
- ベンダー確認: ベンダーが確認したら vendor_confirmed_* を記録する。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..constants import (
    CHANGE_REQUEST_STATUS_LABELS,
    AuditAction,
    ChangeRequestStatus,
    NotificationType,
    OrderStatus,
    RoleCode,
)
from ..database import get_db
from ..deps import AccessScope, forbidden, get_current_user, require_hq, scope_dependency
from ..models import ChangeRequest, Order, OrderItem, User, utcnow
from ..notify import hq_users, notify_users, store_users, vendor_users
from ..schemas import ChangeRequestDecision, ChangeRequestIn, ChangeRequestOut
from ..services import (
    bump_version,
    claim_status_transition,
    compute_quantity,
    consume_idempotency_token,
    get_item_for_user,
    is_after_deadline,
    recalc_order_status,
    record_quantity_change,
    set_item_status,
)

router = APIRouter(prefix="/api/change-requests", tags=["変更申請"])


def _to_out(db: Session, cr: ChangeRequest) -> ChangeRequestOut:
    out = ChangeRequestOut.model_validate(cr)
    out.status_label = CHANGE_REQUEST_STATUS_LABELS.get(
        ChangeRequestStatus(cr.status), cr.status
    )
    order = (
        db.query(Order)
        .options(joinedload(Order.store), joinedload(Order.vendor))
        .filter(Order.id == cr.order_id)
        .first()
    )
    if order:
        out.order_no = order.order_no
        out.store_name = order.store.name if order.store else None
        out.vendor_name = order.vendor.name if order.vendor else None
        out.delivery_date = order.delivery_date
    item = db.query(OrderItem).filter(OrderItem.id == cr.order_item_id).first()
    if item:
        out.product_name = item.product_name
    ids = {cr.requester_id, cr.approver_id} - {None}
    names = {u.id: u.name for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    out.requester_name = names.get(cr.requester_id)
    out.approver_name = names.get(cr.approver_id)
    return out


@router.get("", response_model=list[ChangeRequestOut])
def list_change_requests(
    request_status: str | None = Query(default=None, alias="status"),
    order_id: int | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(scope_dependency),
):
    q = (
        db.query(ChangeRequest)
        .join(Order, Order.id == ChangeRequest.order_id)
        .filter(Order.deleted_at.is_(None))
    )
    # 店舗・ベンダーのデータ分離をここでも効かせる
    if scope.store_id is not None:
        q = q.filter(Order.store_id == scope.store_id)
    if scope.vendor_id is not None:
        q = q.filter(Order.vendor_id == scope.vendor_id)
    if request_status:
        q = q.filter(ChangeRequest.status.in_([s.strip() for s in request_status.split(",")]))
    if order_id:
        q = q.filter(ChangeRequest.order_id == order_id)

    rows = q.order_by(ChangeRequest.requested_at.desc()).limit(limit).all()
    return [_to_out(db, cr) for cr in rows]


@router.post("", response_model=ChangeRequestOut, status_code=status.HTTP_201_CREATED)
def create_change_request(
    payload: ChangeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order, item = get_item_for_user(db, payload.order_item_id, user)

    if user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーは変更申請できません")
    if order.status == str(OrderStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT, "取消済みの発注は変更申請できません")
    if not is_after_deadline(order):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "締め前です。変更申請ではなく発注画面から直接修正してください。",
        )
    if (
        db.query(ChangeRequest)
        .filter(
            ChangeRequest.order_item_id == item.id,
            ChangeRequest.status == str(ChangeRequestStatus.PENDING),
        )
        .first()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "この明細には申請中の変更があります")

    consume_idempotency_token(db, user, payload.client_token, "create_change_request")

    requested_quantity = compute_quantity(item.case_qty, payload.requested_case, payload.requested_loose)
    if (payload.requested_case, payload.requested_loose) == (item.qty_case, item.qty_loose):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "現在の数量と同じです")

    cr = ChangeRequest(
        order_id=order.id,
        order_item_id=item.id,
        before_case=item.qty_case,
        before_loose=item.qty_loose,
        before_quantity=item.quantity,
        requested_case=payload.requested_case,
        requested_loose=payload.requested_loose,
        requested_quantity=requested_quantity,
        reason=payload.reason.strip(),
        status=str(ChangeRequestStatus.PENDING),
        requester_id=user.id,
    )
    db.add(cr)
    db.flush()

    # 申請時点では数量を変えない。ステータスのみ「変更申請中」にする。
    set_item_status(db, order, item, str(OrderStatus.CHANGE_REQUESTED), user,
                    note=f"変更申請: {payload.reason}")
    recalc_order_status(db, order, user)

    log_action(db, user, AuditAction.CHANGE_REQUEST, target_type="change_request", target_id=cr.id,
               detail={"order_no": order.order_no, "商品": item.product_name,
                       "変更前": item.quantity, "変更後": requested_quantity, "理由": payload.reason},
               request=request)
    notify_users(
        db,
        hq_users(db),
        notification_type=NotificationType.CHANGE_REQUESTED,
        title=f"締め後変更申請 {order.order_no} / {item.product_name}",
        body=f"{item.quantity} → {requested_quantity}（理由: {payload.reason}）承認をお願いします。",
        dedup_key=f"change_requested:{cr.id}",
        order_id=order.id,
        order_item_id=item.id,
    )
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr)


@router.post("/{cr_id}/decision", response_model=ChangeRequestOut)
def decide_change_request(
    cr_id: int,
    payload: ChangeRequestDecision,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    """本部／管理者による承認・却下。承認時に初めて数量を更新する。"""
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == cr_id).first()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "変更申請が見つかりません")
    if cr.status != str(ChangeRequestStatus.PENDING):
        raise HTTPException(status.HTTP_409_CONFLICT, "既に処理済みの申請です")
    if not payload.approve and not (payload.reject_reason or "").strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "却下理由を入力してください")

    order = db.query(Order).filter(Order.id == cr.order_id).first()
    item = db.query(OrderItem).filter(OrderItem.id == cr.order_item_id).first()
    if order is None or item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "対象の発注が見つかりません")

    now = utcnow()
    decided_status = str(
        ChangeRequestStatus.APPROVED if payload.approve else ChangeRequestStatus.REJECTED
    )
    # 本部担当者が同時に承認しても1人だけを勝たせる。
    # 上の PENDING 判定だけでは、複数リクエストが同じ PENDING を見て全員通過してしまい、
    # 承認者・承認履歴・通知が多重に記録される。
    if not claim_status_transition(
        db, ChangeRequest, cr.id,
        from_statuses=[str(ChangeRequestStatus.PENDING)],
        to_status=decided_status,
        extra={"approver_id": user.id, "approved_at": now,
               "reject_reason": (payload.reject_reason or "").strip() or None},
    ):
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "この変更申請は既に他の担当者が処理しました。"
        )

    cr.approver_id = user.id
    cr.approved_at = now

    if payload.approve:
        cr.status = str(ChangeRequestStatus.APPROVED)
        before = (item.qty_case, item.qty_loose, item.quantity)
        item.qty_case = cr.requested_case
        item.qty_loose = cr.requested_loose
        item.quantity = cr.requested_quantity
        item.updated_by = user.id
        db.add(item)
        # 変更前数量を保持したまま履歴を残す（削除不可）
        record_quantity_change(
            db, order, item,
            before=before,
            after=(item.qty_case, item.qty_loose, item.quantity),
            user=user,
            reason=cr.reason,
            after_deadline=True,
            change_request_id=cr.id,
            requester_id=cr.requester_id,
            approver_id=user.id,
            approved_at=now,
        )
        set_item_status(db, order, item, str(OrderStatus.CHANGE_APPROVED), user, note="変更承認")
        action, ntype = AuditAction.CHANGE_APPROVE, NotificationType.CHANGE_APPROVED
        title = f"変更承認 {order.order_no} / {item.product_name}"
        body = f"{cr.before_quantity} → {cr.requested_quantity} に変更されました。"
    else:
        cr.status = str(ChangeRequestStatus.REJECTED)
        cr.reject_reason = payload.reject_reason.strip()
        record_quantity_change(
            db, order, item,
            before=(cr.before_case, cr.before_loose, cr.before_quantity),
            after=(cr.before_case, cr.before_loose, cr.before_quantity),
            user=user,
            reason=cr.reason,
            after_deadline=True,
            change_request_id=cr.id,
            requester_id=cr.requester_id,
            approver_id=user.id,
            approved_at=now,
            reject_reason=cr.reject_reason,
        )
        set_item_status(db, order, item, str(OrderStatus.CHANGE_REJECTED), user,
                        note=f"変更却下: {cr.reject_reason}")
        action, ntype = AuditAction.CHANGE_REJECT, NotificationType.CHANGE_REJECTED
        title = f"変更却下 {order.order_no} / {item.product_name}"
        body = f"却下理由: {cr.reject_reason}"

    db.add(cr)
    recalc_order_status(db, order, user)
    bump_version(db, order)
    log_action(db, user, action, target_type="change_request", target_id=cr.id,
               detail={"order_no": order.order_no, "判定": "承認" if payload.approve else "却下"},
               request=request)
    notify_users(
        db,
        store_users(db, order.store_id) + (vendor_users(db, order.vendor_id) if payload.approve else []),
        notification_type=ntype,
        title=title,
        body=body,
        dedup_key=f"change_decision:{cr.id}",
        order_id=order.id,
        order_item_id=item.id,
    )
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr)


@router.post("/{cr_id}/vendor-confirm", response_model=ChangeRequestOut)
def vendor_confirm(
    cr_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """承認済みの変更をベンダーが確認する。ここで正式数量として扱う。"""
    cr = db.query(ChangeRequest).filter(ChangeRequest.id == cr_id).first()
    if cr is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "変更申請が見つかりません")
    order = db.query(Order).filter(Order.id == cr.order_id).first()
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "発注が見つかりません")

    if user.role.code != RoleCode.VENDOR or user.vendor_id != order.vendor_id:
        raise forbidden("担当ベンダーのみ確認できます")
    if cr.status != str(ChangeRequestStatus.APPROVED):
        raise HTTPException(status.HTTP_409_CONFLICT, "承認済みの変更のみ確認できます")
    if cr.vendor_confirmed_at:
        raise HTTPException(status.HTTP_409_CONFLICT, "既に確認済みです")

    now = utcnow()
    cr.vendor_confirmed_by = user.id
    cr.vendor_confirmed_at = now
    db.add(cr)

    item = db.query(OrderItem).filter(OrderItem.id == cr.order_item_id).first()
    if item is not None:
        history = record_quantity_change(
            db, order, item,
            before=(cr.requested_case, cr.requested_loose, cr.requested_quantity),
            after=(cr.requested_case, cr.requested_loose, cr.requested_quantity),
            user=user,
            reason="ベンダー確認",
            after_deadline=True,
            change_request_id=cr.id,
            requester_id=cr.requester_id,
            approver_id=cr.approver_id,
            approved_at=cr.approved_at,
        )
        history.vendor_confirmed_by = user.id
        history.vendor_confirmed_at = now
        db.add(history)
        set_item_status(db, order, item, str(OrderStatus.VENDOR_ACK), user, note="変更内容をベンダー確認")
        recalc_order_status(db, order, user)

    log_action(db, user, AuditAction.VENDOR_RESPONSE, target_type="change_request", target_id=cr.id,
               detail={"操作": "変更内容のベンダー確認", "order_no": order.order_no}, request=request)
    notify_users(
        db,
        store_users(db, order.store_id) + hq_users(db),
        notification_type=NotificationType.CHANGE_APPROVED,
        title=f"変更内容をベンダーが確認 {order.order_no}",
        body="変更後の数量が正式数量として反映されました。",
        dedup_key=f"change_vendor_confirmed:{cr.id}",
        order_id=order.id,
    )
    db.commit()
    db.refresh(cr)
    return _to_out(db, cr)
