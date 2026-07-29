"""認証・権限のための依存関係。

データ分離の要。ここを通らずにDBを引くルータを作らないこと。

原則:
- 店舗ユーザーは自店舗、ベンダーユーザーは自ベンダーに **サーバー側で強制的に** 絞り込む。
- クライアントが store_id / vendor_id を指定しても、自分のスコープ外なら 403 を返す。
  （黙って自分のスコープに読み替えると、他店舗データが無いのか権限が無いのか区別できず、
   実装ミスに気づけないため、明示的に 403 とする。）
"""
from __future__ import annotations

from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from .config import settings
from .constants import CROSS_TENANT_ROLES, RoleCode
from .database import get_db
from .models import RevokedToken, User
from .security import csrf_tokens_match, decode_access_token

CSRF_EXEMPT_PATHS = {"/api/auth/login", "/api/auth/password-reset/request", "/api/auth/password-reset/confirm"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _unauthorized(detail: str = "認証が必要です") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def forbidden(detail: str = "この操作を行う権限がありません") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get(settings.cookie_name)
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise _unauthorized()

    payload = decode_access_token(token)
    if not payload:
        raise _unauthorized("セッションの有効期限が切れました。再度ログインしてください。")

    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        raise _unauthorized()

    user = (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.store), joinedload(User.vendor))
        .filter(User.id == user_id)
        .first()
    )
    if user is None or user.deleted_at is not None:
        raise _unauthorized()
    if not user.is_active:
        raise forbidden("このアカウントは停止されています")

    # --- セッション失効の判定 ---
    # (1) ログアウトしたトークンを個別に失効させる。
    #     iat は秒単位なので、時刻比較だけではログアウトと同じ秒に発行された
    #     トークンを取りこぼす。jti で一意に判定する。
    jti = payload.get("jti")
    if jti and db.query(RevokedToken.id).filter(RevokedToken.jti == jti).first():
        raise _unauthorized("ログアウト済みのセッションです。再度ログインしてください。")

    # (2) パスワード変更・権限変更では、版数を上げて全セッションを一括失効させる。
    if payload.get("sv") != user.session_version:
        raise _unauthorized("セッションは無効化されています。再度ログインしてください。")

    # CSRF: 更新系メソッドは Cookie と ヘッダのトークン一致を必須とする
    if request.method in UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
        cookie_token = request.cookies.get(settings.csrf_cookie_name)
        header_token = request.headers.get("X-CSRF-Token")
        # Cookie を使わない API クライアント（Bearer 認証）は CSRF の対象外
        if request.cookies.get(settings.cookie_name) and not csrf_tokens_match(
            cookie_token, header_token
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="CSRFトークンが不正です"
            )

    request.state.current_user = user
    return user


def require_roles(*roles: RoleCode):
    """指定ロールのみ許可する依存関係を返す。"""
    allowed = {str(r) for r in roles}

    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role.code not in allowed:
            raise forbidden()
        return user

    return _checker


require_admin = require_roles(RoleCode.ADMIN)
require_hq = require_roles(RoleCode.ADMIN, RoleCode.HQ)
require_store_side = require_roles(RoleCode.ADMIN, RoleCode.HQ, RoleCode.STORE)
require_vendor_side = require_roles(RoleCode.ADMIN, RoleCode.HQ, RoleCode.VENDOR)


@dataclass
class AccessScope:
    """このリクエストで実際に適用される絞り込み条件。"""

    user: User
    store_id: int | None       # None = 全店舗
    vendor_id: int | None      # None = 全ベンダー
    can_switch_store: bool
    can_switch_vendor: bool
    role_code: str

    @property
    def is_vendor_user(self) -> bool:
        return self.role_code == RoleCode.VENDOR

    @property
    def is_store_user(self) -> bool:
        return self.role_code == RoleCode.STORE

    @property
    def is_cross_tenant(self) -> bool:
        return self.role_code in {str(r) for r in CROSS_TENANT_ROLES}


def build_scope(
    user: User,
    requested_store_id: int | None = None,
    requested_vendor_id: int | None = None,
) -> AccessScope:
    """要求されたフィルタとユーザー権限を突き合わせ、実効スコープを組み立てる。"""
    role = user.role.code

    if role in {str(r) for r in CROSS_TENANT_ROLES}:
        # 管理者・本部は店舗／ベンダーを自由に切り替えられる（未指定なら全件）
        return AccessScope(
            user=user,
            store_id=requested_store_id,
            vendor_id=requested_vendor_id,
            can_switch_store=True,
            can_switch_vendor=True,
            role_code=role,
        )

    if role == RoleCode.STORE:
        if user.store_id is None:
            raise forbidden("店舗が割り当てられていません")
        if requested_store_id is not None and requested_store_id != user.store_id:
            raise forbidden("他店舗のデータにはアクセスできません")
        # 店舗ユーザーはベンダーでの絞り込み（表示のフィルタ）は許可するが、店舗は固定
        return AccessScope(
            user=user,
            store_id=user.store_id,
            vendor_id=requested_vendor_id,
            can_switch_store=False,
            can_switch_vendor=False,
            role_code=role,
        )

    if role == RoleCode.VENDOR:
        if user.vendor_id is None:
            raise forbidden("ベンダーが割り当てられていません")
        if requested_vendor_id is not None and requested_vendor_id != user.vendor_id:
            raise forbidden("他ベンダーのデータにはアクセスできません")
        # ベンダーユーザーは自ベンダー固定。店舗での絞り込み表示は自ベンダー分に限り可能。
        return AccessScope(
            user=user,
            store_id=requested_store_id,
            vendor_id=user.vendor_id,
            can_switch_store=False,
            can_switch_vendor=False,
            role_code=role,
        )

    raise forbidden()


def scope_dependency(
    request: Request,
    store_id: int | None = None,
    vendor_id: int | None = None,
    user: User = Depends(get_current_user),
) -> AccessScope:
    """クエリパラメータ store_id / vendor_id を権限と突き合わせてスコープ化する。"""
    return build_scope(user, store_id, vendor_id)


def assert_store_access(user: User, store_id: int) -> None:
    """特定の店舗リソースへのアクセス可否を判定する。"""
    role = user.role.code
    if role in {str(r) for r in CROSS_TENANT_ROLES}:
        return
    if role == RoleCode.STORE and user.store_id == store_id:
        return
    if role == RoleCode.VENDOR:
        # ベンダーは店舗を跨いで自社分を見るため、店舗単体では拒否しない
        return
    raise forbidden("他店舗のデータにはアクセスできません")


def assert_vendor_access(user: User, vendor_id: int) -> None:
    role = user.role.code
    if role in {str(r) for r in CROSS_TENANT_ROLES}:
        return
    if role == RoleCode.VENDOR and user.vendor_id == vendor_id:
        return
    if role == RoleCode.STORE:
        return
    raise forbidden("他ベンダーのデータにはアクセスできません")


def assert_order_access(user: User, store_id: int, vendor_id: int) -> None:
    """発注1件へのアクセス権を、店舗軸とベンダー軸の両方で判定する。

    URL / API パラメータを書き換えても他店舗・他ベンダーの発注を開けないようにするための
    最終防衛線。ルータ側で必ず呼ぶこと。
    """
    role = user.role.code
    if role in {str(r) for r in CROSS_TENANT_ROLES}:
        return
    if role == RoleCode.STORE:
        if user.store_id != store_id:
            raise forbidden("他店舗の発注にはアクセスできません")
        return
    if role == RoleCode.VENDOR:
        if user.vendor_id != vendor_id:
            raise forbidden("他ベンダーの発注にはアクセスできません")
        return
    raise forbidden()
