"""マスタ管理API（店舗・ベンダー・商品・ユーザー・締め時間・理由）。

参照範囲:
- ベンダーユーザー … 自ベンダーと自ベンダー商品のみ。他ベンダーは一覧にも出さない。
- 店舗ユーザー   … 発注に必要なベンダー／商品は参照可。ユーザー管理は不可。
- 管理者         … 更新系すべて。本部は参照＋商品/締め時間の更新まで。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..audit import log_action
from ..constants import (
    ROLE_LABELS,
    AuditAction,
    CROSS_TENANT_ROLES,
    DeadlineScope,
    ReasonKind,
    RoleCode,
)
from ..database import get_db
from ..deps import forbidden, get_current_user, require_admin, require_hq
from ..models import (
    Deadline,
    Favorite,
    Product,
    ProductVendor,
    ReasonMaster,
    Role,
    Store,
    User,
    Vendor,
    utcnow,
)
from ..schemas import (
    DeadlineIn,
    DeadlineOut,
    ProductIn,
    ProductOut,
    ReasonIn,
    ReasonOut,
    StoreIn,
    StoreOut,
    UserIn,
    UserOut,
    VendorIn,
    VendorOut,
)
from ..security import hash_password

router = APIRouter(prefix="/api", tags=["マスタ"])


def _is_cross(user: User) -> bool:
    return user.role.code in {str(r) for r in CROSS_TENANT_ROLES}


# --------------------------------------------------------------------------
# 店舗
# --------------------------------------------------------------------------
@router.get("/stores", response_model=list[StoreOut])
def list_stores(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Store).filter(Store.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Store.is_active.is_(True))

    # 店舗ユーザーには自店舗しか返さない（店舗切替UIを作れないようにする）
    if user.role.code == RoleCode.STORE:
        q = q.filter(Store.id == user.store_id)

    return [StoreOut.model_validate(s) for s in q.order_by(Store.code).all()]


@router.post("/stores", response_model=StoreOut, status_code=status.HTTP_201_CREATED)
def create_store(
    payload: StoreIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if db.query(Store).filter(Store.code == payload.code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "同じ店舗コードが既に存在します")
    store = Store(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(store)
    db.flush()
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="store", target_id=store.id,
               detail={"操作": "作成", "code": payload.code}, request=request)
    db.commit()
    return StoreOut.model_validate(store)


@router.put("/stores/{store_id}", response_model=StoreOut)
def update_store(
    store_id: int,
    payload: StoreIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    store = db.query(Store).filter(Store.id == store_id, Store.deleted_at.is_(None)).first()
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "店舗が見つかりません")
    before = {"name": store.name, "is_active": store.is_active}
    for k, v in payload.model_dump().items():
        setattr(store, k, v)
    store.updated_by = user.id
    db.add(store)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="store", target_id=store.id,
               detail={"操作": "更新", "変更前": before}, request=request)
    db.commit()
    return StoreOut.model_validate(store)


@router.delete("/stores/{store_id}")
def delete_store(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """論理削除のみ。取引履歴は残す。"""
    store = db.query(Store).filter(Store.id == store_id, Store.deleted_at.is_(None)).first()
    if not store:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "店舗が見つかりません")
    store.deleted_at = utcnow()
    store.deleted_by = user.id
    store.is_active = False
    db.add(store)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="store", target_id=store.id,
               detail={"操作": "論理削除"}, request=request)
    db.commit()
    return {"message": "店舗を無効化しました"}


# --------------------------------------------------------------------------
# ベンダー
# --------------------------------------------------------------------------
@router.get("/vendors", response_model=list[VendorOut])
def list_vendors(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Vendor).filter(Vendor.deleted_at.is_(None))
    if not include_inactive:
        q = q.filter(Vendor.is_active.is_(True))

    # ベンダーユーザーには自社しか返さない（＝ベンダー切替UIを構成できない）
    if user.role.code == RoleCode.VENDOR:
        q = q.filter(Vendor.id == user.vendor_id)

    return [VendorOut.model_validate(v) for v in q.order_by(Vendor.code).all()]


@router.post("/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
def create_vendor(
    payload: VendorIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if db.query(Vendor).filter(Vendor.code == payload.code).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "同じベンダーコードが既に存在します")
    vendor = Vendor(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(vendor)
    db.flush()
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="vendor", target_id=vendor.id,
               detail={"操作": "作成", "code": payload.code}, request=request)
    db.commit()
    return VendorOut.model_validate(vendor)


@router.put("/vendors/{vendor_id}", response_model=VendorOut)
def update_vendor(
    vendor_id: int,
    payload: VendorIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.deleted_at.is_(None)).first()
    if not vendor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ベンダーが見つかりません")
    before = {"name": vendor.name, "is_active": vendor.is_active}
    for k, v in payload.model_dump().items():
        setattr(vendor, k, v)
    vendor.updated_by = user.id
    db.add(vendor)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="vendor", target_id=vendor.id,
               detail={"操作": "更新", "変更前": before}, request=request)
    db.commit()
    return VendorOut.model_validate(vendor)


@router.delete("/vendors/{vendor_id}")
def delete_vendor(
    vendor_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    vendor = db.query(Vendor).filter(Vendor.id == vendor_id, Vendor.deleted_at.is_(None)).first()
    if not vendor:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ベンダーが見つかりません")
    vendor.deleted_at = utcnow()
    vendor.deleted_by = user.id
    vendor.is_active = False
    db.add(vendor)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="vendor", target_id=vendor.id,
               detail={"操作": "論理削除"}, request=request)
    db.commit()
    return {"message": "ベンダーを無効化しました"}


# --------------------------------------------------------------------------
# 商品
# --------------------------------------------------------------------------
def _product_out(p: Product) -> ProductOut:
    data = ProductOut.model_validate(p)
    data.vendor_name = p.vendor.name if p.vendor else None
    return data


@router.get("/products", response_model=list[ProductOut])
def list_products(
    q: str | None = Query(default=None, description="商品名・JAN・自社コードの部分一致"),
    vendor_id: int | None = None,
    category: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = (
        db.query(Product)
        .options(joinedload(Product.vendor))
        .filter(Product.deleted_at.is_(None))
    )
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))

    # ベンダーユーザーは自ベンダー商品のみ。URLで vendor_id を変えても効かない。
    if user.role.code == RoleCode.VENDOR:
        query = query.filter(Product.vendor_id == user.vendor_id)
        if vendor_id is not None and vendor_id != user.vendor_id:
            raise forbidden("他ベンダーの商品は参照できません")
    elif vendor_id is not None:
        query = query.filter(Product.vendor_id == vendor_id)

    if category:
        query = query.filter(Product.category == category)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(Product.name.like(like), Product.jan_code.like(like), Product.own_code.like(like))
        )

    rows = query.order_by(Product.vendor_id, Product.own_code).offset(offset).limit(limit).all()
    return [_product_out(p) for p in rows]


@router.get("/products/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = db.query(Product.category).filter(
        Product.deleted_at.is_(None), Product.is_active.is_(True), Product.category.isnot(None)
    )
    if user.role.code == RoleCode.VENDOR:
        query = query.filter(Product.vendor_id == user.vendor_id)
    return sorted({row[0] for row in query.distinct().all() if row[0]})


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(
    product_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = (
        db.query(Product)
        .options(joinedload(Product.vendor))
        .filter(Product.id == product_id, Product.deleted_at.is_(None))
        .first()
    )
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品が見つかりません")
    if user.role.code == RoleCode.VENDOR and p.vendor_id != user.vendor_id:
        raise forbidden("他ベンダーの商品は参照できません")
    return _product_out(p)


@router.post("/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(
    payload: ProductIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    if not db.query(Vendor).filter(Vendor.id == payload.vendor_id, Vendor.deleted_at.is_(None)).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "担当ベンダーが存在しません")
    if db.query(Product).filter(Product.own_code == payload.own_code, Product.deleted_at.is_(None)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "同じ自社商品コードが既に存在します")

    product = Product(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(product)
    db.flush()
    # 主ベンダーの関連行を必ず作る（将来の複数ベンダー対応の土台）
    db.add(
        ProductVendor(
            product_id=product.id,
            vendor_id=product.vendor_id,
            is_primary=True,
            cost=product.cost,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="product", target_id=product.id,
               detail={"操作": "作成", "own_code": payload.own_code}, request=request)
    db.commit()
    return _product_out(product)


@router.put("/products/{product_id}", response_model=ProductOut)
def update_product(
    product_id: int,
    payload: ProductIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    product = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品が見つかりません")

    before = {"name": product.name, "vendor_id": product.vendor_id, "cost": float(product.cost or 0)}
    old_vendor_id = product.vendor_id
    for k, v in payload.model_dump().items():
        setattr(product, k, v)
    product.updated_by = user.id
    db.add(product)

    if old_vendor_id != product.vendor_id:
        # 担当ベンダー変更時は関連テーブルも追従させる
        db.query(ProductVendor).filter(
            ProductVendor.product_id == product.id, ProductVendor.is_primary.is_(True)
        ).update({"is_primary": False, "is_active": False})
        link = (
            db.query(ProductVendor)
            .filter(
                ProductVendor.product_id == product.id,
                ProductVendor.vendor_id == product.vendor_id,
            )
            .first()
        )
        if link:
            link.is_primary = True
            link.is_active = True
            db.add(link)
        else:
            db.add(
                ProductVendor(
                    product_id=product.id,
                    vendor_id=product.vendor_id,
                    is_primary=True,
                    cost=product.cost,
                    created_by=user.id,
                    updated_by=user.id,
                )
            )

    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="product", target_id=product.id,
               detail={"操作": "更新", "変更前": before}, request=request)
    db.commit()
    return _product_out(product)


@router.delete("/products/{product_id}")
def delete_product(
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    product = db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first()
    if not product:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品が見つかりません")
    product.deleted_at = utcnow()
    product.deleted_by = user.id
    product.is_active = False
    db.add(product)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="product", target_id=product.id,
               detail={"操作": "論理削除"}, request=request)
    db.commit()
    return {"message": "商品を無効化しました"}


# --------------------------------------------------------------------------
# お気に入り商品（店舗単位）
# --------------------------------------------------------------------------
@router.get("/favorites", response_model=list[ProductOut])
def list_favorites(
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target_store = store_id
    if user.role.code == RoleCode.STORE:
        if store_id is not None and store_id != user.store_id:
            raise forbidden("他店舗のお気に入りは参照できません")
        target_store = user.store_id
    elif user.role.code == RoleCode.VENDOR:
        raise forbidden("ベンダーユーザーはお気に入りを利用できません")
    if target_store is None:
        return []

    rows = (
        db.query(Product)
        .options(joinedload(Product.vendor))
        .join(Favorite, Favorite.product_id == Product.id)
        .filter(Favorite.store_id == target_store, Product.deleted_at.is_(None), Product.is_active.is_(True))
        .order_by(Product.name)
        .all()
    )
    return [_product_out(p) for p in rows]


@router.post("/favorites/{product_id}")
def add_favorite(
    product_id: int,
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target_store = user.store_id if user.role.code == RoleCode.STORE else store_id
    if user.role.code == RoleCode.VENDOR or target_store is None:
        raise forbidden("お気に入りを登録できません")
    if not db.query(Product).filter(Product.id == product_id, Product.deleted_at.is_(None)).first():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品が見つかりません")
    exists = (
        db.query(Favorite)
        .filter(Favorite.store_id == target_store, Favorite.product_id == product_id)
        .first()
    )
    if not exists:
        db.add(Favorite(store_id=target_store, product_id=product_id, created_by=user.id, updated_by=user.id))
        db.commit()
    return {"message": "お気に入りに登録しました"}


@router.delete("/favorites/{product_id}")
def remove_favorite(
    product_id: int,
    store_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    target_store = user.store_id if user.role.code == RoleCode.STORE else store_id
    if user.role.code == RoleCode.VENDOR or target_store is None:
        raise forbidden("お気に入りを操作できません")
    db.query(Favorite).filter(
        Favorite.store_id == target_store, Favorite.product_id == product_id
    ).delete()
    db.commit()
    return {"message": "お気に入りを解除しました"}


# --------------------------------------------------------------------------
# ユーザー（管理者のみ）
# --------------------------------------------------------------------------
def _user_out(u: User) -> UserOut:
    data = UserOut.model_validate(u)
    code = u.role.code if u.role else None
    data.role_code = code
    data.role_label = ROLE_LABELS.get(RoleCode(code), code) if code else None
    data.store_name = u.store.name if u.store else None
    data.vendor_name = u.vendor.name if u.vendor else None
    return data


@router.get("/users", response_model=list[UserOut])
def list_users(
    include_inactive: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    q = (
        db.query(User)
        .options(joinedload(User.role), joinedload(User.store), joinedload(User.vendor))
        .filter(User.deleted_at.is_(None))
    )
    if not include_inactive:
        q = q.filter(User.is_active.is_(True))
    return [_user_out(u) for u in q.order_by(User.id).all()]


def _validate_user_assignment(role_code: str, store_id: int | None, vendor_id: int | None) -> None:
    if role_code == RoleCode.STORE and store_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "店舗担当者には店舗の指定が必要です")
    if role_code == RoleCode.VENDOR and vendor_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ベンダー担当者にはベンダーの指定が必要です")
    if role_code in {RoleCode.ADMIN, RoleCode.HQ} and (store_id or vendor_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "管理者・本部担当者に店舗／ベンダーは割り当てられません"
        )
    if role_code == RoleCode.STORE and vendor_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "店舗担当者にベンダーは割り当てられません")
    if role_code == RoleCode.VENDOR and store_id is not None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ベンダー担当者に店舗は割り当てられません")


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    email = payload.email.lower().strip()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "同じメールアドレスが既に存在します")
    role = db.query(Role).filter(Role.code == payload.role_code).first()
    if not role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "権限が不正です")
    if not payload.password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "初期パスワードを指定してください")
    _validate_user_assignment(payload.role_code, payload.store_id, payload.vendor_id)

    new_user = User(
        email=email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role_id=role.id,
        store_id=payload.store_id,
        vendor_id=payload.vendor_id,
        is_active=payload.is_active,
        phone=payload.phone,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(new_user)
    db.flush()
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="user", target_id=new_user.id,
               detail={"操作": "作成", "email": email, "role": payload.role_code}, request=request)
    db.commit()
    db.refresh(new_user)
    return _user_out(new_user)


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ユーザーが見つかりません")
    role = db.query(Role).filter(Role.code == payload.role_code).first()
    if not role:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "権限が不正です")
    _validate_user_assignment(payload.role_code, payload.store_id, payload.vendor_id)

    was_active = target.is_active
    before_scope = (target.role_id, target.store_id, target.vendor_id)
    target.email = payload.email.lower().strip()
    target.name = payload.name
    target.role_id = role.id
    target.store_id = payload.store_id
    target.vendor_id = payload.vendor_id
    target.is_active = payload.is_active
    target.phone = payload.phone
    if payload.password:
        target.password_hash = hash_password(payload.password)
        target.failed_login_count = 0
        target.locked_until = None
    # 権限・所属・パスワードが変わったら発行済みトークンを失効させる。
    # 参照範囲はロールと所属で決まるため、古いセッションを残すと旧権限で操作できてしまう。
    if (
        payload.password
        or before_scope != (role.id, payload.store_id, payload.vendor_id)
        or (was_active and not payload.is_active)
    ):
        target.session_version += 1
    target.updated_by = user.id
    db.add(target)

    action = AuditAction.USER_SUSPEND if (was_active and not payload.is_active) else AuditAction.MASTER_CHANGE
    log_action(db, user, action, target_type="user", target_id=target.id,
               detail={"操作": "更新", "is_active": payload.is_active}, request=request)
    db.commit()
    db.refresh(target)
    return _user_out(target)


@router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ユーザーが見つかりません")
    target.locked_until = None
    target.failed_login_count = 0
    db.add(target)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="user", target_id=target.id,
               detail={"操作": "ロック解除"}, request=request)
    db.commit()
    db.refresh(target)
    return _user_out(target)


@router.delete("/users/{user_id}")
def suspend_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ユーザーが見つかりません")
    if target.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "自分自身は停止できません")
    target.is_active = False
    target.deleted_at = utcnow()
    target.deleted_by = user.id
    target.session_version += 1   # 発行済みトークンも失効させる
    db.add(target)
    log_action(db, user, AuditAction.USER_SUSPEND, target_type="user", target_id=target.id,
               detail={"操作": "停止"}, request=request)
    db.commit()
    return {"message": "アカウントを停止しました"}


@router.get("/roles")
def list_roles(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return [
        {"id": r.id, "code": r.code, "name": r.name}
        for r in db.query(Role).order_by(Role.id).all()
    ]


# --------------------------------------------------------------------------
# 締め時間
# --------------------------------------------------------------------------
@router.get("/deadlines", response_model=list[DeadlineOut])
def list_deadlines(
    scope: str | None = None,
    vendor_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Deadline).filter(Deadline.deleted_at.is_(None))
    if scope:
        q = q.filter(Deadline.scope == scope)
    # ベンダーユーザーは自社に関係する設定のみ参照
    if user.role.code == RoleCode.VENDOR:
        q = q.filter(
            or_(Deadline.vendor_id == user.vendor_id, Deadline.scope == str(DeadlineScope.SYSTEM))
        )
    elif vendor_id is not None:
        q = q.filter(or_(Deadline.vendor_id == vendor_id, Deadline.scope == str(DeadlineScope.SYSTEM)))
    return [DeadlineOut.model_validate(d) for d in q.order_by(Deadline.scope, Deadline.id).all()]


@router.post("/deadlines", response_model=DeadlineOut, status_code=status.HTTP_201_CREATED)
def create_deadline(
    payload: DeadlineIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    if payload.scope not in {str(s) for s in DeadlineScope}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "scope が不正です")
    if payload.scope == str(DeadlineScope.VENDOR) and payload.vendor_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ベンダー別締めにはベンダーの指定が必要です")
    if payload.scope == str(DeadlineScope.PRODUCT) and payload.product_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "商品別締めには商品の指定が必要です")

    deadline = Deadline(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(deadline)
    db.flush()
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="deadline", target_id=deadline.id,
               detail={"操作": "作成", "scope": payload.scope}, request=request)
    db.commit()
    return DeadlineOut.model_validate(deadline)


@router.put("/deadlines/{deadline_id}", response_model=DeadlineOut)
def update_deadline(
    deadline_id: int,
    payload: DeadlineIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    deadline = db.query(Deadline).filter(Deadline.id == deadline_id, Deadline.deleted_at.is_(None)).first()
    if not deadline:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "締め時間設定が見つかりません")
    for k, v in payload.model_dump().items():
        setattr(deadline, k, v)
    deadline.updated_by = user.id
    db.add(deadline)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="deadline", target_id=deadline.id,
               detail={"操作": "更新"}, request=request)
    db.commit()
    return DeadlineOut.model_validate(deadline)


@router.delete("/deadlines/{deadline_id}")
def delete_deadline(
    deadline_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    deadline = db.query(Deadline).filter(Deadline.id == deadline_id, Deadline.deleted_at.is_(None)).first()
    if not deadline:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "締め時間設定が見つかりません")
    if deadline.scope == str(DeadlineScope.SYSTEM):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "システム標準の締め時間は削除できません")
    deadline.deleted_at = utcnow()
    deadline.deleted_by = user.id
    deadline.is_active = False
    db.add(deadline)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="deadline", target_id=deadline.id,
               detail={"操作": "論理削除"}, request=request)
    db.commit()
    return {"message": "締め時間設定を無効化しました"}


# --------------------------------------------------------------------------
# 理由マスタ
# --------------------------------------------------------------------------
@router.get("/reasons", response_model=list[ReasonOut])
def list_reasons(
    kind: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(ReasonMaster).filter(
        ReasonMaster.deleted_at.is_(None), ReasonMaster.is_active.is_(True)
    )
    if kind:
        q = q.filter(ReasonMaster.kind == kind)
    return [
        ReasonOut.model_validate(r)
        for r in q.order_by(ReasonMaster.kind, ReasonMaster.sort_order, ReasonMaster.id).all()
    ]


@router.post("/reasons", response_model=ReasonOut, status_code=status.HTTP_201_CREATED)
def create_reason(
    payload: ReasonIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    if payload.kind not in {str(k) for k in ReasonKind}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind が不正です")
    if (
        db.query(ReasonMaster)
        .filter(ReasonMaster.kind == payload.kind, ReasonMaster.code == payload.code)
        .first()
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "同じ理由コードが既に存在します")
    reason = ReasonMaster(**payload.model_dump(), created_by=user.id, updated_by=user.id)
    db.add(reason)
    db.flush()
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="reason", target_id=reason.id,
               detail={"操作": "作成"}, request=request)
    db.commit()
    return ReasonOut.model_validate(reason)


@router.delete("/reasons/{reason_id}")
def delete_reason(
    reason_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_hq),
):
    reason = db.query(ReasonMaster).filter(
        ReasonMaster.id == reason_id, ReasonMaster.deleted_at.is_(None)
    ).first()
    if not reason:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "理由が見つかりません")
    reason.deleted_at = utcnow()
    reason.deleted_by = user.id
    reason.is_active = False
    db.add(reason)
    log_action(db, user, AuditAction.MASTER_CHANGE, target_type="reason", target_id=reason.id,
               detail={"操作": "論理削除"}, request=request)
    db.commit()
    return {"message": "理由を無効化しました"}
