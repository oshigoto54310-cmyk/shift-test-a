"""初期テストデータ投入スクリプト（すべて架空データ）。

実在する企業名・店舗名・担当者名・メールアドレス・JANコードは使用していない。
メールドメインは RFC 2606 / RFC 6761 で予約された .invalid / .example を使う。
JAN は自社利用コード帯（先頭 02）の架空値。

使い方:
    python seed.py            # 既存データがある場合は中止
    python seed.py --reset    # 全削除して作り直す
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.constants import (  # noqa: E402
    ChangeRequestStatus,
    DeadlineScope,
    OrderStatus,
    ReasonKind,
    ResponseType,
    RoleCode,
)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.deadlines import resolve_order_deadline  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    ChangeRequest,
    Deadline,
    Favorite,
    IdempotencyKey,
    LoginLog,
    Notification,
    NotificationLog,
    Order,
    OrderHistory,
    OrderItem,
    OrderStatusHistory,
    Product,
    ProductVendor,
    ReasonMaster,
    Role,
    Store,
    User,
    Vendor,
    VendorResponse,
    utcnow,
)
from app.security import hash_password  # noqa: E402

random.seed(20260729)  # 再現性のため固定

DEFAULT_PASSWORD = "Password123!"

ROLES = [
    (RoleCode.ADMIN, "管理者", "全機能を利用できる"),
    (RoleCode.HQ, "本部担当者", "全店舗・全ベンダーを横断して発注を管理する"),
    (RoleCode.STORE, "店舗担当者", "自店舗の発注のみ操作できる"),
    (RoleCode.VENDOR, "ベンダー担当者", "自ベンダーの発注のみ閲覧・回答できる"),
]

STORES = [
    ("ST01", "みどり台店", "架空県架空市みどり台1-1-1", "03-0000-0001"),
    ("ST02", "さくら通り店", "架空県架空市さくら通り2-2-2", "03-0000-0002"),
    ("ST03", "ひばりヶ丘店", "架空県架空市ひばりヶ丘3-3-3", "03-0000-0003"),
]

VENDORS = [
    ("VD01", "架空フーズ株式会社", "取引担当A", "vendor-a@example.invalid", "03-0000-1001"),
    ("VD02", "サンプル物産株式会社", "取引担当B", "vendor-b@example.invalid", "03-0000-1002"),
]

# (自社コード, 商品名, 分類, 規格, ケース入数, 発注単位, バラ可否, 原価, 売価, ベンダー番号)
PRODUCTS = [
    ("P0001", "架空牛乳 1000ml", "日配", "1000ml", 6, "BOTH", True, 158.0, 218.0, 0),
    ("P0002", "架空ヨーグルト プレーン", "日配", "400g", 12, "BOTH", True, 128.0, 178.0, 0),
    ("P0003", "架空とうふ 木綿", "日配", "300g", 20, "BOTH", True, 58.0, 88.0, 0),
    ("P0004", "架空納豆 3個パック", "日配", "45g×3", 24, "CASE", False, 78.0, 108.0, 0),
    ("P0005", "架空たまご Mサイズ", "日配", "10個", 10, "BOTH", True, 198.0, 258.0, 0),
    ("P0006", "架空食パン 6枚切", "パン", "6枚", 8, "BOTH", True, 118.0, 158.0, 0),
    ("P0007", "架空ロールパン", "パン", "5個", 10, "CASE", False, 108.0, 148.0, 0),
    ("P0008", "架空ミックスサラダ", "青果", "150g", 12, "BOTH", True, 98.0, 138.0, 0),
    ("P0009", "架空カットフルーツ", "青果", "200g", 8, "BOTH", True, 228.0, 298.0, 0),
    ("P0010", "架空プリン 3個パック", "デザート", "70g×3", 12, "BOTH", True, 138.0, 188.0, 0),
    ("P0011", "サンプル醤油 1L", "調味料", "1000ml", 12, "CASE", False, 268.0, 348.0, 1),
    ("P0012", "サンプル味噌 750g", "調味料", "750g", 8, "BOTH", True, 258.0, 328.0, 1),
    ("P0013", "サンプルサラダ油 900g", "調味料", "900g", 10, "CASE", False, 328.0, 428.0, 1),
    ("P0014", "サンプル砂糖 1kg", "乾物", "1kg", 20, "BOTH", True, 198.0, 258.0, 1),
    ("P0015", "サンプル小麦粉 1kg", "乾物", "1kg", 20, "BOTH", True, 178.0, 238.0, 1),
    ("P0016", "サンプルパスタ 500g", "乾麺", "500g", 24, "BOTH", True, 158.0, 218.0, 1),
    ("P0017", "サンプル即席麺 5食", "乾麺", "5食", 12, "CASE", False, 328.0, 428.0, 1),
    ("P0018", "サンプル缶詰 ツナ", "缶詰", "70g×3", 24, "BOTH", True, 268.0, 348.0, 1),
    ("P0019", "サンプルレトルトカレー", "レトルト", "200g", 30, "BOTH", True, 128.0, 178.0, 1),
    ("P0020", "サンプル冷凍餃子", "冷凍", "12個", 12, "BOTH", True, 208.0, 278.0, 1),
]

CHANGE_REASONS = [
    ("SALES_CHANGE", "売上予測の変更"),
    ("WEATHER", "天候による需要変動"),
    ("EVENT", "催事・チラシ対応"),
    ("STOCK", "在庫過多・在庫不足"),
    ("INPUT_MISS", "入力誤り"),
    ("OTHER", "その他"),
]

SHORTAGE_REASONS = [
    ("PRODUCTION", "生産遅延"),
    ("MATERIAL", "原材料不足"),
    ("LOGISTICS", "物流遅延"),
    ("DEMAND", "需要集中による在庫切れ"),
    ("DISCONTINUED", "終売・規格変更"),
    ("OTHER", "その他"),
]


def jan_for(index: int) -> str:
    """架空のJANコード（自社利用コード帯 02 で始まる13桁）。"""
    body = f"02{index:010d}"
    total = sum((3 if i % 2 else 1) * int(d) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


def reset_database() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def already_seeded(db) -> bool:
    return db.query(User).first() is not None


def seed() -> None:
    db = SessionLocal()
    try:
        # ---------------- ロール ----------------
        roles: dict[str, Role] = {}
        for code, name, desc in ROLES:
            role = Role(code=str(code), name=name, description=desc)
            db.add(role)
            roles[str(code)] = role
        db.flush()

        # ---------------- 店舗・ベンダー ----------------
        stores: list[Store] = []
        for code, name, addr, phone in STORES:
            s = Store(code=code, name=name, address=addr, phone=phone, is_active=True)
            db.add(s)
            stores.append(s)

        vendors: list[Vendor] = []
        for code, name, contact, email, phone in VENDORS:
            v = Vendor(code=code, name=name, contact_name=contact, email=email, phone=phone, is_active=True)
            db.add(v)
            vendors.append(v)
        db.flush()

        # ---------------- ユーザー ----------------
        users: dict[str, User] = {}

        def add_user(email, name, role_code, store=None, vendor=None):
            u = User(
                email=email,
                name=name,
                password_hash=hash_password(DEFAULT_PASSWORD),
                role_id=roles[str(role_code)].id,
                store_id=store.id if store else None,
                vendor_id=vendor.id if vendor else None,
                is_active=True,
            )
            db.add(u)
            users[email] = u
            return u

        admin = add_user("admin@example.invalid", "システム管理者", RoleCode.ADMIN)
        add_user("hq1@example.invalid", "本部 一郎", RoleCode.HQ)
        add_user("hq2@example.invalid", "本部 二郎", RoleCode.HQ)

        store_users: dict[int, list[User]] = {}
        for idx, store in enumerate(stores, start=1):
            store_users[store.id] = [
                add_user(f"store{idx}a@example.invalid", f"{store.name} 担当A", RoleCode.STORE, store=store),
                add_user(f"store{idx}b@example.invalid", f"{store.name} 担当B", RoleCode.STORE, store=store),
            ]

        vendor_users: dict[int, list[User]] = {}
        for idx, vendor in enumerate(vendors, start=1):
            vendor_users[vendor.id] = [
                add_user(f"vendor{idx}a@example.invalid", f"{vendor.name} 担当A", RoleCode.VENDOR, vendor=vendor),
                add_user(f"vendor{idx}b@example.invalid", f"{vendor.name} 担当B", RoleCode.VENDOR, vendor=vendor),
            ]
        db.flush()

        # ---------------- 商品 ----------------
        products: list[Product] = []
        for i, (own, name, cat, spec, case_qty, unit, loose, cost, price, vidx) in enumerate(PRODUCTS, start=1):
            p = Product(
                jan_code=jan_for(i),
                own_code=own,
                name=name,
                category=cat,
                spec=spec,
                case_qty=case_qty,
                order_unit=unit,
                allow_loose=loose,
                cost=cost,
                price=price,
                valid_from=date.today() - timedelta(days=365),
                vendor_id=vendors[vidx].id,
                is_active=True,
                created_by=admin.id,
                updated_by=admin.id,
            )
            db.add(p)
            products.append(p)
        db.flush()
        for p in products:
            db.add(ProductVendor(product_id=p.id, vendor_id=p.vendor_id, is_primary=True, cost=p.cost))

        # 原価未登録の警告を確認できるよう1商品だけ原価を空にする
        products[-1].cost = None
        db.add(products[-1])

        # ---------------- 締め時間 ----------------
        db.add(Deadline(scope=str(DeadlineScope.SYSTEM), rough_days_before=3, rough_time="12:00",
                        final_days_before=1, final_time="12:00", reply_days_before=1,
                        reply_time="15:00", is_active=True, note="システム標準"))
        db.add(Deadline(scope=str(DeadlineScope.VENDOR), vendor_id=vendors[0].id,
                        rough_days_before=3, rough_time="10:00", final_days_before=1,
                        final_time="10:00", reply_days_before=1, reply_time="14:00",
                        is_active=True, note="日配のため早め"))
        db.add(Deadline(scope=str(DeadlineScope.PRODUCT), product_id=products[0].id,
                        vendor_id=vendors[0].id, rough_days_before=4, rough_time="09:00",
                        final_days_before=2, final_time="09:00", reply_days_before=1,
                        reply_time="12:00", is_active=True, note="牛乳は個別締め"))

        # ---------------- 理由マスタ ----------------
        for order_no, (code, label) in enumerate(CHANGE_REASONS):
            db.add(ReasonMaster(kind=str(ReasonKind.CHANGE), code=code, label=label, sort_order=order_no))
        for order_no, (code, label) in enumerate(SHORTAGE_REASONS):
            db.add(ReasonMaster(kind=str(ReasonKind.SHORTAGE), code=code, label=label, sort_order=order_no))

        # ---------------- お気に入り ----------------
        for store in stores:
            for p in products[:3]:
                db.add(Favorite(store_id=store.id, product_id=p.id))
        db.flush()

        # ---------------- 発注データ 30件 ----------------
        today = date.today()
        orders: list[Order] = []
        seq = 0
        # 過去（締め後）10件・直近（締め前）20件を作る
        date_plan = [today - timedelta(days=d) for d in (5, 4, 3)] + [
            today + timedelta(days=d) for d in (2, 3, 4, 5, 6, 7)
        ]

        while len(orders) < 30:
            for delivery_date in date_plan:
                if len(orders) >= 30:
                    break
                store = stores[len(orders) % len(stores)]
                vendor = vendors[len(orders) % len(vendors)]
                vendor_products = [p for p in products if p.vendor_id == vendor.id]
                picked = random.sample(vendor_products, k=random.randint(2, 4))
                seq += 1

                is_past = delivery_date < today
                status = str(OrderStatus.CONFIRMED if is_past else
                             (OrderStatus.CONFIRMED if seq % 4 else OrderStatus.DRAFT))
                item_status = (
                    str(OrderStatus.VENDOR_PENDING)
                    if status == str(OrderStatus.CONFIRMED)
                    else str(OrderStatus.DRAFT)
                )

                creator = store_users[store.id][0]
                order = Order(
                    order_no=f"{delivery_date:%Y%m%d}-{store.code}-{seq:03d}",
                    store_id=store.id,
                    vendor_id=vendor.id,
                    delivery_date=delivery_date,
                    status=status,
                    note=None,
                    created_by=creator.id,
                    updated_by=creator.id,
                )
                dl = resolve_order_deadline(
                    db, delivery_date=delivery_date, vendor_id=vendor.id,
                    product_ids=[p.id for p in picked],
                )
                order.rough_deadline_at = dl.rough_deadline_at
                order.deadline_at = dl.final_deadline_at
                order.reply_deadline_at = dl.reply_deadline_at
                if status == str(OrderStatus.CONFIRMED):
                    order.confirmed_at = utcnow()
                    order.confirmed_by = creator.id
                db.add(order)
                db.flush()

                db.add(OrderStatusHistory(order_id=order.id, status_before=None,
                                          status_after=status, changed_by=creator.id,
                                          note="初期データ投入"))

                for p in picked:
                    qty_case = random.randint(1, 5)
                    qty_loose = random.randint(0, max(p.case_qty - 1, 0)) if p.allow_loose else 0
                    quantity = p.case_qty * qty_case + qty_loose
                    item = OrderItem(
                        order_id=order.id,
                        product_id=p.id,
                        jan_code=p.jan_code,
                        product_name=p.name,
                        spec=p.spec,
                        order_unit=p.order_unit,
                        case_qty=p.case_qty,
                        cost=p.cost,
                        qty_case=qty_case,
                        qty_loose=qty_loose,
                        quantity=quantity,
                        status=item_status,
                        created_by=creator.id,
                        updated_by=creator.id,
                    )
                    db.add(item)
                    db.flush()
                    db.add(OrderHistory(order_id=order.id, order_item_id=item.id,
                                        case_before=0, loose_before=0, qty_before=0,
                                        case_after=qty_case, loose_after=qty_loose,
                                        qty_after=quantity, reason="新規登録",
                                        changed_by=creator.id, is_after_deadline=False))
                    db.add(OrderStatusHistory(order_id=order.id, order_item_id=item.id,
                                              status_before=None, status_after=item_status,
                                              changed_by=creator.id, note="初期データ投入"))
                orders.append(order)
        db.flush()

        confirmed_orders = [o for o in orders if o.status == str(OrderStatus.CONFIRMED)]

        # ---------------- 欠品データ 3件 ----------------
        shortage_targets = []
        for order in confirmed_orders:
            if len(shortage_targets) >= 3:
                break
            items = [i for i in order.items if i.status == str(OrderStatus.VENDOR_PENDING)]
            if items:
                shortage_targets.append((order, items[0]))

        for idx, (order, item) in enumerate(shortage_targets):
            responder = vendor_users[order.vendor_id][0]
            db.add(VendorResponse(
                order_id=order.id, order_item_id=item.id, vendor_id=order.vendor_id,
                response_type=str(ResponseType.SHORTAGE), ordered_qty=item.quantity,
                deliverable_qty=0, shortage_qty=item.quantity,
                shortage_reason=SHORTAGE_REASONS[idx % len(SHORTAGE_REASONS)][1],
                next_available_date=order.delivery_date + timedelta(days=3),
                has_substitute=False, responder_id=responder.id, is_latest=True,
            ))
            db.add(OrderStatusHistory(order_id=order.id, order_item_id=item.id,
                                      status_before=item.status, status_after=str(OrderStatus.SHORTAGE),
                                      changed_by=responder.id, note="ベンダー回答: 欠品"))
            item.status = str(OrderStatus.SHORTAGE)
            item.confirmed_quantity = 0
            db.add(item)
            order.status = str(OrderStatus.SHORTAGE)
            db.add(order)

        # ---------------- 一部納品データ 3件 ----------------
        partial_targets = []
        used = {id(i) for _, i in shortage_targets}
        for order in confirmed_orders:
            if len(partial_targets) >= 3:
                break
            items = [
                i for i in order.items
                if i.status == str(OrderStatus.VENDOR_PENDING) and id(i) not in used and i.quantity > 2
            ]
            if items:
                partial_targets.append((order, items[0]))
                used.add(id(items[0]))

        for idx, (order, item) in enumerate(partial_targets):
            responder = vendor_users[order.vendor_id][1]
            deliverable = max(item.quantity // 2, 1)
            db.add(VendorResponse(
                order_id=order.id, order_item_id=item.id, vendor_id=order.vendor_id,
                response_type=str(ResponseType.PARTIAL), ordered_qty=item.quantity,
                deliverable_qty=deliverable, shortage_qty=item.quantity - deliverable,
                reason=SHORTAGE_REASONS[(idx + 1) % len(SHORTAGE_REASONS)][1],
                responder_id=responder.id, is_latest=True,
            ))
            db.add(OrderStatusHistory(order_id=order.id, order_item_id=item.id,
                                      status_before=item.status, status_after=str(OrderStatus.PARTIAL),
                                      changed_by=responder.id, note="ベンダー回答: 一部納品"))
            item.status = str(OrderStatus.PARTIAL)
            item.confirmed_quantity = deliverable
            db.add(item)
            if order.status != str(OrderStatus.SHORTAGE):
                order.status = str(OrderStatus.PARTIAL)
                db.add(order)

        # ---------------- 締め後変更申請 3件 ----------------
        now = utcnow()
        past_orders = [
            o for o in orders
            if o.deadline_at and o.deadline_at < now and o.status != str(OrderStatus.DRAFT)
        ]
        cr_count = 0
        for order in past_orders:
            if cr_count >= 3:
                break
            items = [i for i in order.items if id(i) not in used]
            if not items:
                continue
            item = items[0]
            used.add(id(item))
            requester = store_users[order.store_id][0]
            new_case = item.qty_case + 1
            new_quantity = item.case_qty * new_case + item.qty_loose
            cr = ChangeRequest(
                order_id=order.id, order_item_id=item.id,
                before_case=item.qty_case, before_loose=item.qty_loose,
                before_quantity=item.quantity,
                requested_case=new_case, requested_loose=item.qty_loose,
                requested_quantity=new_quantity,
                reason=CHANGE_REASONS[cr_count % len(CHANGE_REASONS)][1],
                status=str(ChangeRequestStatus.PENDING), requester_id=requester.id,
            )
            db.add(cr)
            db.add(OrderStatusHistory(order_id=order.id, order_item_id=item.id,
                                      status_before=item.status,
                                      status_after=str(OrderStatus.CHANGE_REQUESTED),
                                      changed_by=requester.id, note="締め後変更申請"))
            item.status = str(OrderStatus.CHANGE_REQUESTED)
            db.add(item)
            order.status = str(OrderStatus.CHANGE_REQUESTED)
            db.add(order)
            cr_count += 1

        db.commit()

        print("=" * 64)
        print("初期テストデータを投入しました（すべて架空データ）")
        print("=" * 64)
        print(f"店舗       : {len(stores)}")
        print(f"ベンダー   : {len(vendors)}")
        print(f"ユーザー   : {len(users)}")
        print(f"商品       : {len(products)}")
        print(f"発注       : {len(orders)}")
        print(f"欠品       : {len(shortage_targets)}")
        print(f"一部納品   : {len(partial_targets)}")
        print(f"変更申請   : {cr_count}")
        print("-" * 64)
        print(f"共通パスワード: {DEFAULT_PASSWORD}")
        print("管理者    : admin@example.invalid")
        print("本部      : hq1@example.invalid / hq2@example.invalid")
        print("店舗      : store1a@example.invalid ... store3b@example.invalid")
        print("ベンダー  : vendor1a@example.invalid ... vendor2b@example.invalid")
        print("=" * 64)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="初期テストデータを投入する")
    parser.add_argument("--reset", action="store_true", help="既存データを全削除して作り直す")
    args = parser.parse_args()

    if args.reset:
        reset_database()
    else:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            if already_seeded(db):
                print("既にデータが存在します。作り直す場合は --reset を付けてください。")
                return
        finally:
            db.close()

    seed()


if __name__ == "__main__":
    main()
