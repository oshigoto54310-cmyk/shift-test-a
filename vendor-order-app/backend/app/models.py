"""SQLAlchemy モデル定義。

方針:
- 主要マスタ／取引テーブルは created_at / updated_at / created_by / updated_by を持つ。
- 論理削除を基本とし、取引履歴（*_histories, *_logs, vendor_responses, change_requests）は
  物理削除も論理削除もしない（削除用カラム・APIを設けない）。
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    """タイムゾーン非依存で扱えるよう、UTCのnaive datetimeを返す。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AuditMixin:
    """全主要テーブル共通の監査カラム。"""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SoftDeleteMixin:
    """論理削除。物理削除は行わない。"""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    deleted_by: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


# --------------------------------------------------------------------------
# マスタ
# --------------------------------------------------------------------------
class Role(Base, AuditMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))

    users: Mapped[list["User"]] = relationship(back_populates="role")


class Store(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list["User"]] = relationship(back_populates="store")


class Vendor(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    users: Mapped[list["User"]] = relationship(back_populates="vendor")
    products: Mapped[list["Product"]] = relationship(back_populates="vendor")


class User(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"), nullable=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    password_reset_token: Mapped[str | None] = mapped_column(String(255), index=True)
    password_reset_expires: Mapped[datetime | None] = mapped_column(DateTime)
    # セッション版数。トークンにこの値を埋め込み、一致しないトークンを無効とする。
    # パスワード変更・パスワード再設定・権限や所属の変更・アカウント停止で +1 する。
    # 時刻比較だと JWT の iat が秒単位のため同じ秒に発行されたトークンを取りこぼすが、
    # 版数なら取りこぼしがない。
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    role: Mapped["Role"] = relationship(back_populates="users")
    store: Mapped["Store | None"] = relationship(back_populates="users")
    vendor: Mapped["Vendor | None"] = relationship(back_populates="users")

    @property
    def role_code(self) -> str:
        return self.role.code


class Product(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    jan_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    own_code: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(60), index=True)
    spec: Mapped[str | None] = mapped_column(String(80))
    case_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # ケース入数
    order_unit: Mapped[str] = mapped_column(String(10), default="CASE", nullable=False)
    allow_loose: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)  # バラ発注可否
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))   # 原価
    price: Mapped[float | None] = mapped_column(Numeric(12, 2))  # 売価
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)

    vendor: Mapped["Vendor"] = relationship(back_populates="products")
    vendor_links: Mapped[list["ProductVendor"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_products_vendor_active", "vendor_id", "is_active"),)


class ProductVendor(Base, AuditMixin):
    """商品とベンダーの関連。将来の複数ベンダー対応用。

    現状は products.vendor_id が担当ベンダー（主）で、ここには主ベンダーを is_primary=True で
    必ず1件持たせる。副ベンダーを追加しても既存ロジックは主ベンダーで動く。
    """

    __tablename__ = "product_vendors"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    vendor_product_code: Mapped[str | None] = mapped_column(String(40))
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    product: Mapped["Product"] = relationship(back_populates="vendor_links")

    __table_args__ = (UniqueConstraint("product_id", "vendor_id", name="uq_product_vendor"),)


class Deadline(Base, AuditMixin, SoftDeleteMixin):
    """締め時間設定。scope により適用範囲が変わる。

    優先順位: PRODUCT > VENDOR > SYSTEM
    delivery_date が設定されている行は、その納品日にのみ適用される（同scope内で最優先）。
    """

    __tablename__ = "deadlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id"), index=True)
    delivery_date: Mapped[date | None] = mapped_column(Date, index=True)

    rough_days_before: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    rough_time: Mapped[str] = mapped_column(String(5), default="12:00", nullable=False)
    final_days_before: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    final_time: Mapped[str] = mapped_column(String(5), default="12:00", nullable=False)
    reply_days_before: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    reply_time: Mapped[str] = mapped_column(String(5), default="15:00", nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class ReasonMaster(Base, AuditMixin, SoftDeleteMixin):
    """変更理由・欠品理由マスタ。"""

    __tablename__ = "reason_masters"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (UniqueConstraint("kind", "code", name="uq_reason_kind_code"),)


# --------------------------------------------------------------------------
# 発注
# --------------------------------------------------------------------------
class Order(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    delivery_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime)       # 最終締め（UTC）
    rough_deadline_at: Mapped[datetime | None] = mapped_column(DateTime)  # 概算締め（UTC）
    reply_deadline_at: Mapped[datetime | None] = mapped_column(DateTime)  # ベンダー回答期限（UTC）
    note: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmed_by: Mapped[int | None] = mapped_column(Integer)
    # 楽観ロック用。更新のたびに +1 する。
    # クライアントが古い version を送ってきたら 409 を返し、静かな上書きを防ぐ。
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    store: Mapped["Store"] = relationship()
    vendor: Mapped["Vendor"] = relationship()
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id"
    )

    __table_args__ = (
        Index("ix_orders_store_vendor_date", "store_id", "vendor_id", "delivery_date"),
    )


class OrderItem(Base, AuditMixin, SoftDeleteMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)

    # 発注時点のスナップショット（マスタ変更の影響を受けないようにする）
    jan_code: Mapped[str] = mapped_column(String(20), nullable=False)
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(80))
    order_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    case_qty: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 2))

    qty_case: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # ケース数
    qty_loose: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # バラ数
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)   # 合計バラ換算数量

    confirmed_quantity: Mapped[int | None] = mapped_column(Integer)  # ベンダー回答後の確定数量
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(Text)

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()

    __table_args__ = (Index("ix_order_items_order_product", "order_id", "product_id"),)


class Favorite(Base, AuditMixin):
    """お気に入り商品（店舗単位）。"""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    __table_args__ = (UniqueConstraint("store_id", "product_id", name="uq_favorite"),)


# --------------------------------------------------------------------------
# 履歴（削除不可）
# --------------------------------------------------------------------------
class OrderHistory(Base):
    """数量変更履歴。締め前・締め後を問わず、数量が動いたら必ず1行残す。"""

    __tablename__ = "order_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), index=True)

    qty_before: Mapped[int | None] = mapped_column(Integer)
    qty_after: Mapped[int | None] = mapped_column(Integer)
    case_before: Mapped[int | None] = mapped_column(Integer)
    case_after: Mapped[int | None] = mapped_column(Integer)
    loose_before: Mapped[int | None] = mapped_column(Integer)
    loose_after: Mapped[int | None] = mapped_column(Integer)

    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    is_after_deadline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    change_request_id: Mapped[int | None] = mapped_column(Integer, index=True)
    requester_id: Mapped[int | None] = mapped_column(Integer)
    approver_id: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    vendor_confirmed_by: Mapped[int | None] = mapped_column(Integer)
    vendor_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"), index=True)
    status_before: Mapped[str | None] = mapped_column(String(20))
    status_after: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[int | None] = mapped_column(Integer)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class VendorResponse(Base):
    """ベンダー回答。上書きせず追記で履歴を残す（最新行が現在の回答）。"""

    __tablename__ = "vendor_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id"), nullable=False, index=True
    )
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    response_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    ordered_qty: Mapped[int | None] = mapped_column(Integer)
    deliverable_qty: Mapped[int | None] = mapped_column(Integer)
    shortage_qty: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)

    # 欠品時
    shortage_reason: Mapped[str | None] = mapped_column(Text)
    next_available_date: Mapped[date | None] = mapped_column(Date)
    has_substitute: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 代替商品提案
    sub_product_name: Mapped[str | None] = mapped_column(String(150))
    sub_jan_code: Mapped[str | None] = mapped_column(String(20))
    sub_spec: Mapped[str | None] = mapped_column(String(80))
    sub_cost: Mapped[float | None] = mapped_column(Numeric(12, 2))
    sub_deliverable_qty: Mapped[int | None] = mapped_column(Integer)
    sub_delivery_date: Mapped[date | None] = mapped_column(Date)
    sub_comment: Mapped[str | None] = mapped_column(Text)
    sub_approved_by: Mapped[int | None] = mapped_column(Integer)   # 代替は本部承認後に確定
    sub_approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    sub_rejected_by: Mapped[int | None] = mapped_column(Integer)
    sub_rejected_at: Mapped[datetime | None] = mapped_column(DateTime)

    comment: Mapped[str | None] = mapped_column(Text)
    responder_id: Mapped[int] = mapped_column(Integer, nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    is_latest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)


class ChangeRequest(Base):
    """締め後の数量変更申請。承認されるまで発注数量は書き換えない。"""

    __tablename__ = "change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id"), nullable=False, index=True
    )

    before_case: Mapped[int] = mapped_column(Integer, nullable=False)
    before_loose: Mapped[int] = mapped_column(Integer, nullable=False)
    before_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_case: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_loose: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    reason: Mapped[str] = mapped_column(Text, nullable=False)  # 変更理由は必須
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    requester_id: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    approver_id: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    reject_reason: Mapped[str | None] = mapped_column(Text)
    vendor_confirmed_by: Mapped[int | None] = mapped_column(Integer)
    vendor_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


# --------------------------------------------------------------------------
# 通知・ログ（削除不可）
# --------------------------------------------------------------------------
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(Integer)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    # 同じ通知を重複送信しないための一意キー
    dedup_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "dedup_key", name="uq_notification_dedup"),)


class NotificationLog(Base):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("notifications.id"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)  # APP / EMAIL
    to_address: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # SENT/SKIPPED/FAILED
    error: Mapped[str | None] = mapped_column(Text)
    dedup_key: Mapped[str | None] = mapped_column(String(200), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class AuditLog(Base):
    """操作ログ。削除不可。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255))
    role_code: Mapped[str | None] = mapped_column(String(20))
    store_id: Mapped[int | None] = mapped_column(Integer, index=True)
    vendor_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(60))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)


class RevokedToken(Base):
    """ログアウトしたトークンの失効リスト。

    JWT はサーバー側に状態を持たないため、Cookie を消すだけでは
    既に手元にあるトークンを使い続けられてしまう。
    ログアウト時に発行済みトークンの jti をここへ記録して個別に失効させる。

    有効期限を過ぎた行は定期ジョブが削除する（残しても意味がないため）。
    ユーザー単位で一括失効させたい場合（パスワード変更・権限変更）は
    users.session_version を使う。
    """

    __tablename__ = "revoked_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class IdempotencyKey(Base):
    """二重送信防止。クライアントが発行したトークンを一度だけ受け付ける。"""

    __tablename__ = "idempotency_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(80), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(80), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "token", name="uq_idempotency_user_token"),)


class LoginLog(Base):
    __tablename__ = "login_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    failure_reason: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(60))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
