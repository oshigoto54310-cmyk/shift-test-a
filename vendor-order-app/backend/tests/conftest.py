"""テスト共通のフィクスチャ。

テストごとに独立した一時SQLiteを使い、本番／開発DBを汚さない。
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# アプリ読み込み前に環境変数を差し替える（settings は起動時に確定するため）
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.name}"
os.environ["SECRET_KEY"] = "test-secret-key-for-automated-tests"
os.environ["ENVIRONMENT"] = "test"
os.environ["MAIL_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.constants import DeadlineScope, OrderStatus, ReasonKind, RoleCode  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.deadlines import resolve_order_deadline  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Deadline,
    Order,
    OrderItem,
    OrderStatusHistory,
    Product,
    ProductVendor,
    ReasonMaster,
    Role,
    Store,
    User,
    Vendor,
    utcnow,
)
from app.security import hash_password  # noqa: E402

PASSWORD = "TestPassword123!"


@pytest.fixture(scope="session", autouse=True)
def _database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _build_fixture_data()
    yield
    Base.metadata.drop_all(bind=engine)
    try:
        os.unlink(_TMP_DB.name)
    except OSError:
        pass


def _build_fixture_data() -> None:
    """架空のテストデータ。実在の企業・店舗・担当者・JANは使わない。"""
    db = SessionLocal()
    try:
        roles = {}
        for code, name in [
            (RoleCode.ADMIN, "管理者"), (RoleCode.HQ, "本部担当者"),
            (RoleCode.STORE, "店舗担当者"), (RoleCode.VENDOR, "ベンダー担当者"),
        ]:
            r = Role(code=str(code), name=name)
            db.add(r)
            roles[str(code)] = r
        db.flush()

        store_a = Store(code="TA", name="テスト店舗A", is_active=True)
        store_b = Store(code="TB", name="テスト店舗B", is_active=True)
        vendor_a = Vendor(code="VA", name="テストベンダーA", is_active=True)
        vendor_b = Vendor(code="VB", name="テストベンダーB", is_active=True)
        db.add_all([store_a, store_b, vendor_a, vendor_b])
        db.flush()

        def user(email, name, role, store=None, vendor=None):
            u = User(
                email=email, name=name, password_hash=hash_password(PASSWORD),
                role_id=roles[str(role)].id,
                store_id=store.id if store else None,
                vendor_id=vendor.id if vendor else None,
                is_active=True,
            )
            db.add(u)
            return u

        user("admin@test.invalid", "管理者", RoleCode.ADMIN)
        user("hq@test.invalid", "本部担当", RoleCode.HQ)
        user("storea@test.invalid", "店舗A担当", RoleCode.STORE, store=store_a)
        user("storeb@test.invalid", "店舗B担当", RoleCode.STORE, store=store_b)
        user("vendora@test.invalid", "ベンダーA担当", RoleCode.VENDOR, vendor=vendor_a)
        user("vendorb@test.invalid", "ベンダーB担当", RoleCode.VENDOR, vendor=vendor_b)
        user("locked@test.invalid", "ロック確認用", RoleCode.STORE, store=store_a)
        db.flush()

        # 締め時間: システム標準のみ（納品日前日12:00）
        db.add(Deadline(
            scope=str(DeadlineScope.SYSTEM), rough_days_before=3, rough_time="12:00",
            final_days_before=1, final_time="12:00", reply_days_before=1, reply_time="15:00",
            is_active=True,
        ))

        for i, (kind, code, label) in enumerate([
            (ReasonKind.CHANGE, "SALES", "売上予測の変更"),
            (ReasonKind.SHORTAGE, "PRODUCTION", "生産遅延"),
        ]):
            db.add(ReasonMaster(kind=str(kind), code=code, label=label, sort_order=i))

        # 商品: ベンダーAに3件、ベンダーBに2件
        specs = [
            ("TA01", "テスト商品A1", vendor_a, 10, "BOTH", True, 100.0),
            ("TA02", "テスト商品A2", vendor_a, 6, "BOTH", True, 200.0),
            ("TA03", "テスト商品A3", vendor_a, 12, "CASE", False, 300.0),
            ("TB01", "テスト商品B1", vendor_b, 8, "BOTH", True, 150.0),
            ("TB02", "テスト商品B2", vendor_b, 20, "BOTH", True, 250.0),
        ]
        for i, (own, name, vendor, case_qty, unit, loose, cost) in enumerate(specs, start=1):
            p = Product(
                jan_code=f"020000000{i:03d}", own_code=own, name=name, category="テスト分類",
                spec="1個", case_qty=case_qty, order_unit=unit, allow_loose=loose,
                cost=cost, price=cost * 1.3, vendor_id=vendor.id, is_active=True,
                valid_from=date.today() - timedelta(days=30),
            )
            db.add(p)
            db.flush()
            db.add(ProductVendor(product_id=p.id, vendor_id=vendor.id, is_primary=True, cost=cost))

        db.commit()
    finally:
        db.close()


# --------------------------------------------------------------------------
# クライアント
# --------------------------------------------------------------------------
def make_client(email: str | None = None) -> TestClient:
    client = TestClient(app)
    if email:
        res = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        assert res.status_code == 200, res.text
        # CSRF: double submit cookie 方式なので、Cookie の値をヘッダにも載せる
        client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    return client


@pytest.fixture
def anon():
    return make_client()


@pytest.fixture
def admin():
    return make_client("admin@test.invalid")


@pytest.fixture
def hq():
    return make_client("hq@test.invalid")


@pytest.fixture
def store_a():
    return make_client("storea@test.invalid")


@pytest.fixture
def store_b():
    return make_client("storeb@test.invalid")


@pytest.fixture
def vendor_a():
    return make_client("vendora@test.invalid")


@pytest.fixture
def vendor_b():
    return make_client("vendorb@test.invalid")


# --------------------------------------------------------------------------
# ヘルパ
# --------------------------------------------------------------------------
def ids(db_model, **filters) -> list[int]:
    db = SessionLocal()
    try:
        q = db.query(db_model.id)
        for k, v in filters.items():
            q = q.filter(getattr(db_model, k) == v)
        return [r[0] for r in q.all()]
    finally:
        db.close()


def get_products(client, vendor_name: str | None = None) -> list[dict]:
    rows = client.get("/api/products").json()
    if vendor_name:
        rows = [r for r in rows if r["vendor_name"] == vendor_name]
    return rows


def future_date(days: int = 5) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def create_order(client, product_ids: list[int], *, delivery_date=None, confirm=False,
                 store_id=None, qty_case=2, qty_loose=0) -> list[dict]:
    payload = {
        "delivery_date": delivery_date or future_date(),
        "items": [
            {"product_id": pid, "qty_case": qty_case, "qty_loose": qty_loose}
            for pid in product_ids
        ],
        "confirm": confirm,
    }
    if store_id:
        payload["store_id"] = store_id
    res = client.post("/api/orders", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def force_deadline_passed(order_id: int) -> None:
    """締め時間を過去にずらして「締め後」状態を作る。"""
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        past = utcnow() - timedelta(hours=2)
        order.deadline_at = past
        order.rough_deadline_at = past - timedelta(days=1)
        db.add(order)
        db.commit()
    finally:
        db.close()


def order_items(order_id: int) -> list[OrderItem]:
    db = SessionLocal()
    try:
        return db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    finally:
        db.close()
