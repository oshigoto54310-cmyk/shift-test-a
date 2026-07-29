"""API入出力スキーマ。"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

# 形式のみを検証するメールアドレス型。
# pydantic の EmailStr は .invalid / .example などの予約ドメインを弾いてしまい、
# 架空データ（RFC 2606 で「テスト用に使え」とされているドメイン）を登録できないため、
# 到達可能性は検証せず形式だけを見る。
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9]([A-Za-z0-9.\-]*[A-Za-z0-9])?\.[A-Za-z]{2,}$")


def _normalize_email(value: str) -> str:
    value = (value or "").strip().lower()
    if len(value) > 255 or not _EMAIL_RE.match(value):
        raise ValueError("メールアドレスの形式が正しくありません")
    return value


EmailStr = Annotated[str, AfterValidator(_normalize_email)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# 認証
# --------------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MeResponse(BaseModel):
    id: int
    email: str
    name: str
    role_code: str
    role_label: str
    store_id: int | None
    store_name: str | None
    vendor_id: int | None
    vendor_name: str | None
    can_switch_vendor: bool
    can_switch_store: bool
    last_login_at: datetime | None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=200)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


# --------------------------------------------------------------------------
# マスタ
# --------------------------------------------------------------------------
class StoreOut(ORMModel):
    id: int
    code: str
    name: str
    address: str | None = None
    phone: str | None = None
    is_active: bool


class StoreIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    address: str | None = None
    phone: str | None = None
    is_active: bool = True
    note: str | None = None


class VendorOut(ORMModel):
    id: int
    code: str
    name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool


class VendorIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool = True
    note: str | None = None


class ProductOut(ORMModel):
    id: int
    jan_code: str
    own_code: str
    name: str
    category: str | None = None
    spec: str | None = None
    case_qty: int
    order_unit: str
    allow_loose: bool
    cost: float | None = None
    price: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    vendor_id: int
    vendor_name: str | None = None
    is_active: bool
    note: str | None = None
    updated_at: datetime | None = None


class ProductIn(BaseModel):
    jan_code: str = Field(min_length=8, max_length=20)
    own_code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    category: str | None = None
    spec: str | None = None
    case_qty: int = Field(default=1, ge=1)
    order_unit: str = "CASE"
    allow_loose: bool = True
    cost: float | None = None
    price: float | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    vendor_id: int
    is_active: bool = True
    note: str | None = None


class UserOut(ORMModel):
    id: int
    email: str
    name: str
    role_code: str | None = None
    role_label: str | None = None
    store_id: int | None = None
    store_name: str | None = None
    vendor_id: int | None = None
    vendor_name: str | None = None
    is_active: bool
    last_login_at: datetime | None = None
    failed_login_count: int = 0
    locked_until: datetime | None = None


class UserIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role_code: str
    store_id: int | None = None
    vendor_id: int | None = None
    is_active: bool = True
    phone: str | None = None


class DeadlineOut(ORMModel):
    id: int
    scope: str
    vendor_id: int | None = None
    product_id: int | None = None
    delivery_date: date | None = None
    rough_days_before: int
    rough_time: str
    final_days_before: int
    final_time: str
    reply_days_before: int
    reply_time: str
    is_active: bool
    note: str | None = None


class DeadlineIn(BaseModel):
    scope: str
    vendor_id: int | None = None
    product_id: int | None = None
    delivery_date: date | None = None
    rough_days_before: int = Field(default=3, ge=0, le=60)
    rough_time: str = "12:00"
    final_days_before: int = Field(default=1, ge=0, le=60)
    final_time: str = "12:00"
    reply_days_before: int = Field(default=1, ge=0, le=60)
    reply_time: str = "15:00"
    is_active: bool = True
    note: str | None = None


class ReasonOut(ORMModel):
    id: int
    kind: str
    code: str
    label: str
    sort_order: int
    is_active: bool


class ReasonIn(BaseModel):
    kind: str
    code: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=100)
    sort_order: int = 0
    is_active: bool = True


# --------------------------------------------------------------------------
# 発注
# --------------------------------------------------------------------------
class OrderItemIn(BaseModel):
    product_id: int
    qty_case: int = Field(default=0, ge=0, le=99999)
    qty_loose: int = Field(default=0, ge=0, le=99999)
    note: str | None = None


def _reject_duplicate_products(items: list[OrderItemIn]) -> list[OrderItemIn]:
    """同じ商品を複数行に分けて送らせない。

    事前チェック（/validate）と登録（POST /orders）で同じ規則を使う。
    ここがずれると「事前チェックは通ったのに登録で弾かれる」ことになる。
    """
    ids = [i.product_id for i in items]
    if len(ids) != len(set(ids)):
        raise ValueError("同じ商品が複数行に含まれています。1商品につき1行にまとめてください。")
    return items


class OrderCreate(BaseModel):
    store_id: int | None = None      # 本部が代理登録する場合に指定
    vendor_id: int | None = None     # 未指定なら商品から自動判定
    delivery_date: date
    note: str | None = None
    items: list[OrderItemIn] = Field(min_length=1)
    confirm: bool = False            # true なら登録と同時に発注確定
    client_token: str | None = None  # 二重送信防止トークン

    @field_validator("items")
    @classmethod
    def _unique_products(cls, v: list[OrderItemIn]) -> list[OrderItemIn]:
        return _reject_duplicate_products(v)


class OrderItemUpdate(BaseModel):
    id: int | None = None            # 既存明細を更新する場合
    product_id: int
    qty_case: int = Field(default=0, ge=0, le=99999)
    qty_loose: int = Field(default=0, ge=0, le=99999)
    note: str | None = None
    reason: str | None = None        # 数量変更理由（締め前は任意）


class OrderUpdate(BaseModel):
    note: str | None = None
    items: list[OrderItemUpdate] = Field(min_length=1)
    client_token: str | None = None
    # 画面が読み込んだ時点の version。必須。
    # 他の担当者が先に更新していれば 409 を返し、静かな上書きを防ぐ。
    version: int = Field(ge=1)


class OrderItemOut(ORMModel):
    id: int
    order_id: int
    product_id: int
    jan_code: str
    product_name: str
    spec: str | None = None
    order_unit: str
    case_qty: int
    cost: float | None = None
    qty_case: int
    qty_loose: int
    quantity: int
    confirmed_quantity: int | None = None
    status: str
    status_label: str | None = None
    note: str | None = None
    latest_response: dict[str, Any] | None = None


class OrderOut(ORMModel):
    id: int
    order_no: str
    store_id: int
    store_name: str | None = None
    vendor_id: int
    vendor_name: str | None = None
    delivery_date: date
    status: str
    status_label: str | None = None
    deadline_at: datetime | None = None
    rough_deadline_at: datetime | None = None
    reply_deadline_at: datetime | None = None
    is_after_deadline: bool = False
    note: str | None = None
    confirmed_at: datetime | None = None
    total_quantity: int = 0
    item_count: int = 0
    items: list[OrderItemOut] = []
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OrderValidationWarning(BaseModel):
    code: str
    message: str
    product_id: int | None = None
    level: str = "WARN"   # WARN / ERROR


class OrderValidateRequest(BaseModel):
    store_id: int | None = None
    delivery_date: date
    items: list[OrderItemIn]

    @field_validator("items")
    @classmethod
    def _unique_products(cls, v: list[OrderItemIn]) -> list[OrderItemIn]:
        return _reject_duplicate_products(v)


class OrderValidateResponse(BaseModel):
    warnings: list[OrderValidationWarning]
    blocking: bool


class OrderConfirmRequest(BaseModel):
    client_token: str | None = None


class OrderCancelRequest(BaseModel):
    reason: str = Field(min_length=1)


# --------------------------------------------------------------------------
# ベンダー回答
# --------------------------------------------------------------------------
class VendorAckRequest(BaseModel):
    """受注確認（発注書を見た、の意思表示）。"""

    order_id: int
    comment: str | None = None


class VendorResponseIn(BaseModel):
    order_item_id: int
    response_type: str
    deliverable_qty: int | None = Field(default=None, ge=0)
    reason: str | None = None
    shortage_reason: str | None = None
    next_available_date: date | None = None
    has_substitute: bool = False
    sub_product_name: str | None = None
    sub_jan_code: str | None = None
    sub_spec: str | None = None
    sub_cost: float | None = Field(default=None, ge=0)   # 原価に負の値は入れさせない
    sub_deliverable_qty: int | None = Field(default=None, ge=0, le=999999)
    sub_delivery_date: date | None = None
    sub_comment: str | None = None
    comment: str | None = None
    client_token: str | None = None


class VendorResponseOut(ORMModel):
    id: int
    order_id: int
    order_item_id: int
    vendor_id: int
    response_type: str
    response_label: str | None = None
    ordered_qty: int | None = None
    deliverable_qty: int | None = None
    shortage_qty: int | None = None
    reason: str | None = None
    shortage_reason: str | None = None
    next_available_date: date | None = None
    has_substitute: bool = False
    sub_product_name: str | None = None
    sub_jan_code: str | None = None
    sub_spec: str | None = None
    sub_cost: float | None = None
    sub_deliverable_qty: int | None = None
    sub_delivery_date: date | None = None
    sub_comment: str | None = None
    sub_approved_at: datetime | None = None
    sub_rejected_at: datetime | None = None
    comment: str | None = None
    responder_id: int
    responder_name: str | None = None
    responded_at: datetime
    is_latest: bool = True


class SubstituteDecision(BaseModel):
    approve: bool
    comment: str | None = None


# --------------------------------------------------------------------------
# 変更申請
# --------------------------------------------------------------------------
class ChangeRequestIn(BaseModel):
    order_item_id: int
    requested_case: int = Field(default=0, ge=0, le=99999)
    requested_loose: int = Field(default=0, ge=0, le=99999)
    reason: str = Field(min_length=1)  # 変更理由は必須
    client_token: str | None = None


class ChangeRequestDecision(BaseModel):
    approve: bool
    reject_reason: str | None = None


class ChangeRequestOut(ORMModel):
    id: int
    order_id: int
    order_no: str | None = None
    order_item_id: int
    product_name: str | None = None
    store_name: str | None = None
    vendor_name: str | None = None
    delivery_date: date | None = None
    before_case: int
    before_loose: int
    before_quantity: int
    requested_case: int
    requested_loose: int
    requested_quantity: int
    reason: str
    status: str
    status_label: str | None = None
    requester_id: int
    requester_name: str | None = None
    requested_at: datetime
    approver_id: int | None = None
    approver_name: str | None = None
    approved_at: datetime | None = None
    reject_reason: str | None = None
    vendor_confirmed_at: datetime | None = None


# --------------------------------------------------------------------------
# 履歴・通知
# --------------------------------------------------------------------------
class OrderHistoryOut(ORMModel):
    id: int
    order_id: int
    order_item_id: int | None = None
    order_no: str | None = None
    product_name: str | None = None
    qty_before: int | None = None
    qty_after: int | None = None
    case_before: int | None = None
    case_after: int | None = None
    loose_before: int | None = None
    loose_after: int | None = None
    reason: str | None = None
    changed_by: int | None = None
    changed_by_name: str | None = None
    changed_at: datetime
    is_after_deadline: bool
    requester_id: int | None = None
    approver_id: int | None = None
    approved_at: datetime | None = None
    reject_reason: str | None = None
    vendor_confirmed_by: int | None = None
    vendor_confirmed_at: datetime | None = None


class StatusHistoryOut(ORMModel):
    id: int
    order_id: int
    order_item_id: int | None = None
    order_no: str | None = None
    status_before: str | None = None
    status_after: str
    status_before_label: str | None = None
    status_after_label: str | None = None
    changed_by: int | None = None
    changed_by_name: str | None = None
    changed_at: datetime
    note: str | None = None


class AuditLogOut(ORMModel):
    id: int
    user_id: int | None = None
    user_email: str | None = None
    role_code: str | None = None
    action: str
    action_label: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    detail: str | None = None
    ip_address: str | None = None
    created_at: datetime


class NotificationOut(ORMModel):
    id: int
    type: str
    type_label: str | None = None
    title: str
    body: str | None = None
    order_id: int | None = None
    is_read: bool
    created_at: datetime


class NotificationLogOut(ORMModel):
    id: int
    user_id: int | None = None
    channel: str
    to_address: str | None = None
    type: str
    status: str
    error: str | None = None
    sent_at: datetime


class LoginLogOut(ORMModel):
    id: int
    user_id: int | None = None
    email: str
    success: bool
    failure_reason: str | None = None
    ip_address: str | None = None
    created_at: datetime


# --------------------------------------------------------------------------
# ダッシュボード / 集計
# --------------------------------------------------------------------------
class DashboardOut(BaseModel):
    today_deadline_count: int
    unconfirmed_count: int
    vendor_pending_count: int
    shortage_count: int
    partial_count: int
    substitute_count: int
    change_request_count: int
    reply_overdue_count: int
    delivery_date: date | None = None
    store_id: int | None = None
    vendor_id: int | None = None


class VendorSummaryRow(BaseModel):
    product_id: int
    jan_code: str
    product_name: str
    spec: str | None = None
    order_unit: str
    case_qty: int
    total_quantity: int
    total_case: int
    total_loose: int
    store_breakdown: list[dict[str, Any]]


class PagedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[Any]
