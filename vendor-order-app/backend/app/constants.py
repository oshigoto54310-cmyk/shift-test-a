"""業務上の区分値。DBには文字列コードで保存し、表示名は日本語ラベルで返す。"""
from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    ADMIN = "ADMIN"       # 管理者
    HQ = "HQ"             # 本部担当者
    STORE = "STORE"       # 店舗担当者
    VENDOR = "VENDOR"     # ベンダー担当者


ROLE_LABELS = {
    RoleCode.ADMIN: "管理者",
    RoleCode.HQ: "本部担当者",
    RoleCode.STORE: "店舗担当者",
    RoleCode.VENDOR: "ベンダー担当者",
}

# 全店舗・全ベンダーを横断して閲覧できるロール
CROSS_TENANT_ROLES = {RoleCode.ADMIN, RoleCode.HQ}


class OrderStatus(StrEnum):
    DRAFT = "DRAFT"                        # 下書き
    PLANNED = "PLANNED"                    # 発注予定
    CONFIRMED = "CONFIRMED"                # 発注確定
    VENDOR_PENDING = "VENDOR_PENDING"      # ベンダー未確認
    VENDOR_ACK = "VENDOR_ACK"              # ベンダー確認済み
    PARTIAL = "PARTIAL"                    # 一部納品
    SHORTAGE = "SHORTAGE"                  # 欠品
    SUBSTITUTE = "SUBSTITUTE"              # 代替提案
    DELIVERED = "DELIVERED"                # 納品確定
    CHANGE_REQUESTED = "CHANGE_REQUESTED"  # 変更申請中
    CHANGE_APPROVED = "CHANGE_APPROVED"    # 変更承認済み
    CHANGE_REJECTED = "CHANGE_REJECTED"    # 変更却下
    CANCELLED = "CANCELLED"                # 取消


ORDER_STATUS_LABELS = {
    OrderStatus.DRAFT: "下書き",
    OrderStatus.PLANNED: "発注予定",
    OrderStatus.CONFIRMED: "発注確定",
    OrderStatus.VENDOR_PENDING: "ベンダー未確認",
    OrderStatus.VENDOR_ACK: "ベンダー確認済み",
    OrderStatus.PARTIAL: "一部納品",
    OrderStatus.SHORTAGE: "欠品",
    OrderStatus.SUBSTITUTE: "代替提案",
    OrderStatus.DELIVERED: "納品確定",
    OrderStatus.CHANGE_REQUESTED: "変更申請中",
    OrderStatus.CHANGE_APPROVED: "変更承認済み",
    OrderStatus.CHANGE_REJECTED: "変更却下",
    OrderStatus.CANCELLED: "取消",
}

# 締め前として数量を直接編集してよいステータス。
# ベンダーが納品可否を回答した後（一部納品・欠品・代替提案・納品確定）は、
# 回答の前提が崩れるため締め前であっても直接編集させない。
EDITABLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.PLANNED,
    OrderStatus.CONFIRMED,
    OrderStatus.VENDOR_PENDING,
    OrderStatus.VENDOR_ACK,
}

# 取消してよいステータス。納品確定済みは店舗から取消できない。
CANCELLABLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.PLANNED,
    OrderStatus.CONFIRMED,
    OrderStatus.VENDOR_PENDING,
    OrderStatus.VENDOR_ACK,
    OrderStatus.SHORTAGE,
    OrderStatus.CHANGE_REJECTED,
}

# ベンダーが納品可否を回答済みで、発注内容が確定に向かっているステータス
VENDOR_ANSWERED_STATUSES = {
    OrderStatus.PARTIAL,
    OrderStatus.SHORTAGE,
    OrderStatus.SUBSTITUTE,
    OrderStatus.DELIVERED,
}

# 確定済みとしてベンダーに公開されるステータス
VENDOR_VISIBLE_STATUSES = {
    OrderStatus.CONFIRMED,
    OrderStatus.VENDOR_PENDING,
    OrderStatus.VENDOR_ACK,
    OrderStatus.PARTIAL,
    OrderStatus.SHORTAGE,
    OrderStatus.SUBSTITUTE,
    OrderStatus.DELIVERED,
    OrderStatus.CHANGE_REQUESTED,
    OrderStatus.CHANGE_APPROVED,
    OrderStatus.CHANGE_REJECTED,
}


class ResponseType(StrEnum):
    FULL = "FULL"              # 全数納品可能
    PARTIAL = "PARTIAL"        # 一部納品可能
    SHORTAGE = "SHORTAGE"      # 欠品
    SUBSTITUTE = "SUBSTITUTE"  # 代替商品提案
    CHECKING = "CHECKING"      # 確認中
    CONSULT = "CONSULT"        # 要相談


RESPONSE_TYPE_LABELS = {
    ResponseType.FULL: "全数納品可能",
    ResponseType.PARTIAL: "一部納品可能",
    ResponseType.SHORTAGE: "欠品",
    ResponseType.SUBSTITUTE: "代替商品提案",
    ResponseType.CHECKING: "確認中",
    ResponseType.CONSULT: "要相談",
}


class ChangeRequestStatus(StrEnum):
    PENDING = "PENDING"     # 申請中
    APPROVED = "APPROVED"   # 承認済み
    REJECTED = "REJECTED"   # 却下
    CANCELLED = "CANCELLED"  # 取下げ


CHANGE_REQUEST_STATUS_LABELS = {
    ChangeRequestStatus.PENDING: "申請中",
    ChangeRequestStatus.APPROVED: "承認済み",
    ChangeRequestStatus.REJECTED: "却下",
    ChangeRequestStatus.CANCELLED: "取下げ",
}


class DeadlineScope(StrEnum):
    SYSTEM = "SYSTEM"    # システム標準
    VENDOR = "VENDOR"    # ベンダー別
    PRODUCT = "PRODUCT"  # 商品別


class OrderUnit(StrEnum):
    CASE = "CASE"    # ケース単位
    PIECE = "PIECE"  # バラ単位
    BOTH = "BOTH"    # ケース・バラ併用


ORDER_UNIT_LABELS = {
    OrderUnit.CASE: "ケース",
    OrderUnit.PIECE: "バラ",
    OrderUnit.BOTH: "ケース＋バラ",
}


class ReasonKind(StrEnum):
    CHANGE = "CHANGE"      # 変更理由
    SHORTAGE = "SHORTAGE"  # 欠品理由


class NotificationType(StrEnum):
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_QTY_CHANGED = "ORDER_QTY_CHANGED"
    DEADLINE_24H = "DEADLINE_24H"
    DEADLINE_1H = "DEADLINE_1H"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    VENDOR_UNCONFIRMED = "VENDOR_UNCONFIRMED"
    VENDOR_REPLY_OVERDUE = "VENDOR_REPLY_OVERDUE"
    PARTIAL_DELIVERY = "PARTIAL_DELIVERY"
    SHORTAGE = "SHORTAGE"
    SUBSTITUTE = "SUBSTITUTE"
    CHANGE_REQUESTED = "CHANGE_REQUESTED"
    CHANGE_APPROVED = "CHANGE_APPROVED"
    CHANGE_REJECTED = "CHANGE_REJECTED"
    DELIVERY_FIXED = "DELIVERY_FIXED"


NOTIFICATION_LABELS = {
    NotificationType.ORDER_CREATED: "新規発注登録",
    NotificationType.ORDER_QTY_CHANGED: "発注数量変更",
    NotificationType.DEADLINE_24H: "締め時間24時間前",
    NotificationType.DEADLINE_1H: "締め時間1時間前",
    NotificationType.ORDER_CONFIRMED: "発注確定",
    NotificationType.VENDOR_UNCONFIRMED: "ベンダー未確認",
    NotificationType.VENDOR_REPLY_OVERDUE: "ベンダー回答期限超過",
    NotificationType.PARTIAL_DELIVERY: "一部納品",
    NotificationType.SHORTAGE: "欠品",
    NotificationType.SUBSTITUTE: "代替提案",
    NotificationType.CHANGE_REQUESTED: "締め後変更申請",
    NotificationType.CHANGE_APPROVED: "変更承認",
    NotificationType.CHANGE_REJECTED: "変更却下",
    NotificationType.DELIVERY_FIXED: "納品確定",
}


class AuditAction(StrEnum):
    LOGIN = "LOGIN"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    ORDER_CREATE = "ORDER_CREATE"
    ORDER_UPDATE = "ORDER_UPDATE"
    ORDER_CONFIRM = "ORDER_CONFIRM"
    ORDER_CANCEL = "ORDER_CANCEL"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    CHANGE_APPROVE = "CHANGE_APPROVE"
    CHANGE_REJECT = "CHANGE_REJECT"
    VENDOR_RESPONSE = "VENDOR_RESPONSE"
    VENDOR_SHORTAGE = "VENDOR_SHORTAGE"
    VENDOR_SUBSTITUTE = "VENDOR_SUBSTITUTE"
    EXPORT_EXCEL = "EXPORT_EXCEL"
    EXPORT_CSV = "EXPORT_CSV"
    EXPORT_PDF = "EXPORT_PDF"
    MASTER_CHANGE = "MASTER_CHANGE"
    USER_SUSPEND = "USER_SUSPEND"


AUDIT_ACTION_LABELS = {
    AuditAction.LOGIN: "ログイン",
    AuditAction.LOGIN_FAILED: "ログイン失敗",
    AuditAction.LOGOUT: "ログアウト",
    AuditAction.ORDER_CREATE: "発注作成",
    AuditAction.ORDER_UPDATE: "発注修正",
    AuditAction.ORDER_CONFIRM: "発注確定",
    AuditAction.ORDER_CANCEL: "発注取消",
    AuditAction.CHANGE_REQUEST: "締め後変更申請",
    AuditAction.CHANGE_APPROVE: "変更承認",
    AuditAction.CHANGE_REJECT: "変更却下",
    AuditAction.VENDOR_RESPONSE: "ベンダー回答",
    AuditAction.VENDOR_SHORTAGE: "欠品回答",
    AuditAction.VENDOR_SUBSTITUTE: "代替提案",
    AuditAction.EXPORT_EXCEL: "Excel出力",
    AuditAction.EXPORT_CSV: "CSV出力",
    AuditAction.EXPORT_PDF: "PDF出力",
    AuditAction.MASTER_CHANGE: "マスタ変更",
    AuditAction.USER_SUSPEND: "ユーザー停止",
}
