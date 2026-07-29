"""IDOR（連番IDの書き換えによる不正アクセス）の網羅テスト。

監査方針:
「画面に出さない」ではなく「サーバー側で取得・更新できない」ことを確認する。
主要リソースについて、他ベンダー・他店舗のIDを直接指定した場合に
データが返らない／更新されないことを検証する。
"""
from __future__ import annotations

import pytest

from app.database import SessionLocal
from app.models import (
    ChangeRequest,
    Deadline,
    Notification,
    Order,
    OrderItem,
    Product,
    VendorResponse,
)

from .conftest import create_order, force_deadline_passed, future_date, get_products


@pytest.fixture(scope="module")
def other_side(request):
    """店舗B×ベンダーBの発注・明細・回答・変更申請をひととおり作る。"""
    from .conftest import make_client

    store_b = make_client("storeb@test.invalid")
    vendor_b = make_client("vendorb@test.invalid")
    hq = make_client("hq@test.invalid")

    products = get_products(store_b, "テストベンダーB")
    order = create_order(
        store_b, [products[0]["id"]], confirm=True, qty_case=3, delivery_date=future_date(90)
    )[0]
    item = store_b.get(f"/api/orders/{order['id']}").json()["items"][0]

    vendor_b.post("/api/vendor/ack", json={"order_id": order["id"]})
    response = vendor_b.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "他社の代替品", "sub_deliverable_qty": 1,
    }).json()

    cr_order = create_order(
        store_b, [products[1]["id"]], confirm=True, qty_case=2, delivery_date=future_date(91)
    )[0]
    force_deadline_passed(cr_order["id"])
    cr_item = store_b.get(f"/api/orders/{cr_order['id']}").json()["items"][0]
    change_request = store_b.post("/api/change-requests", json={
        "order_item_id": cr_item["id"], "requested_case": 5, "requested_loose": 0,
        "reason": "他社の申請",
    }).json()

    db = SessionLocal()
    try:
        notification = (
            db.query(Notification)
            .join(Order, Order.id == Notification.order_id)
            .filter(Order.store_id == 2)
            .first()
        )
        notification_id = notification.id if notification else None
        deadline_id = db.query(Deadline).first().id
    finally:
        db.close()

    return {
        "order_id": order["id"],
        "item_id": item["id"],
        "product_id": products[0]["id"],
        "response_id": response["id"],
        "cr_id": change_request["id"],
        "cr_order_id": cr_order["id"],
        "notification_id": notification_id,
        "deadline_id": deadline_id,
    }


# --------------------------------------------------------------------------
# ベンダーユーザーから見た他ベンダーのリソース
# --------------------------------------------------------------------------
def test_他ベンダーの発注と明細に到達できない(vendor_a, other_side):
    assert vendor_a.get(f"/api/orders/{other_side['order_id']}").status_code == 403
    assert vendor_a.get(f"/api/orders/{other_side['order_id']}/editable").status_code == 403
    assert vendor_a.post("/api/vendor/ack", json={"order_id": other_side["order_id"]}).status_code == 403
    assert vendor_a.post("/api/vendor/responses", json={
        "order_item_id": other_side["item_id"], "response_type": "FULL",
    }).status_code == 403


def test_他ベンダーの商品に到達できない(vendor_a, other_side):
    assert vendor_a.get(f"/api/products/{other_side['product_id']}").status_code == 403
    assert vendor_a.get("/api/products", params={"vendor_id": 2}).status_code == 403
    # 更新系はロール自体が拒否される
    assert vendor_a.put(f"/api/products/{other_side['product_id']}", json={
        "jan_code": "0299999999999", "own_code": "HACK", "name": "改ざん",
        "case_qty": 1, "order_unit": "CASE", "vendor_id": 2,
    }).status_code == 403
    assert vendor_a.delete(f"/api/products/{other_side['product_id']}").status_code == 403


def test_他ベンダーの回答と代替提案に到達できない(vendor_a, other_side):
    rows = vendor_a.get("/api/vendor/responses", params={"limit": 500}).json()
    assert all(r["vendor_id"] == 1 for r in rows)
    assert all(r["id"] != other_side["response_id"] for r in rows)
    # 代替提案の承認は本部権限。ベンダーは他社のものにも自社のものにも触れない。
    assert vendor_a.post(
        f"/api/vendor/responses/{other_side['response_id']}/substitute-decision",
        json={"approve": True},
    ).status_code == 403


def test_他ベンダーの変更申請に到達できない(vendor_a, other_side):
    rows = vendor_a.get("/api/change-requests", params={"limit": 500}).json()
    assert all(r["id"] != other_side["cr_id"] for r in rows)
    assert vendor_a.post(
        f"/api/change-requests/{other_side['cr_id']}/decision", json={"approve": True}
    ).status_code == 403
    assert vendor_a.post(
        f"/api/change-requests/{other_side['cr_id']}/vendor-confirm"
    ).status_code == 403


def test_他ベンダーの履歴に到達できない(vendor_a, other_side):
    qty = vendor_a.get("/api/histories/quantity", params={"order_id": other_side["order_id"]}).json()
    assert qty == []
    status_rows = vendor_a.get("/api/histories/status", params={"order_id": other_side["order_id"]}).json()
    assert status_rows == []


def test_他ベンダーの出力に到達できない(vendor_a):
    for endpoint in ("orders", "product-summary", "shortages", "partials", "unanswered",
                     "change-requests", "order-histories", "delivery-date-summary"):
        res = vendor_a.get(f"/api/exports/{endpoint}", params={"fmt": "csv", "vendor_id": 2})
        assert res.status_code == 403, f"{endpoint} で他ベンダー指定が通った"


# --------------------------------------------------------------------------
# 店舗ユーザーから見た他店舗のリソース
# --------------------------------------------------------------------------
def test_他店舗の発注と明細に到達できない(store_a, other_side):
    assert store_a.get(f"/api/orders/{other_side['order_id']}").status_code == 403
    assert store_a.get(f"/api/orders/{other_side['order_id']}/editable").status_code == 403
    assert store_a.post(f"/api/orders/{other_side['order_id']}/confirm", json={}).status_code == 403
    assert store_a.post(
        f"/api/orders/{other_side['order_id']}/cancel", json={"reason": "不正"}
    ).status_code == 403
    assert store_a.put(f"/api/orders/{other_side['order_id']}", json={
        "version": 1,
        "items": [{"id": other_side["item_id"], "product_id": other_side["product_id"],
                   "qty_case": 99, "qty_loose": 0}],
    }).status_code == 403


def test_他店舗の明細に変更申請できない(store_a, other_side):
    res = store_a.post("/api/change-requests", json={
        "order_item_id": other_side["item_id"], "requested_case": 9,
        "requested_loose": 0, "reason": "不正",
    })
    assert res.status_code == 403


def test_他店舗の変更申請を操作できない(store_a, other_side):
    rows = store_a.get("/api/change-requests", params={"limit": 500}).json()
    assert all(r["id"] != other_side["cr_id"] for r in rows)
    assert store_a.post(
        f"/api/change-requests/{other_side['cr_id']}/decision", json={"approve": True}
    ).status_code == 403


def test_他店舗のお気に入りを操作できない(store_a):
    assert store_a.get("/api/favorites", params={"store_id": 2}).status_code == 403
    assert store_a.post("/api/favorites/1", params={"store_id": 2}).status_code in (200, 403)
    # store_id を指定しても自店舗に登録されること（他店舗には入らない）
    db = SessionLocal()
    try:
        from app.models import Favorite

        assert db.query(Favorite).filter(Favorite.store_id == 2).count() == 0
    finally:
        db.close()


def test_他店舗の履歴と出力に到達できない(store_a, other_side):
    assert store_a.get("/api/histories/quantity", params={"order_id": other_side["order_id"]}).json() == []
    assert store_a.get("/api/exports/orders", params={"fmt": "csv", "store_id": 2}).status_code == 403


# --------------------------------------------------------------------------
# 通知・管理系
# --------------------------------------------------------------------------
def test_他人の通知を既読にできない(store_a, other_side):
    if other_side["notification_id"] is None:
        pytest.skip("他店舗向けの通知が生成されていない")
    before = SessionLocal()
    try:
        target = before.query(Notification).filter(
            Notification.id == other_side["notification_id"]
        ).first()
        was_read = target.is_read
        owner_id = target.user_id
    finally:
        before.close()

    store_a.post(f"/api/notifications/{other_side['notification_id']}/read")

    after = SessionLocal()
    try:
        target = after.query(Notification).filter(
            Notification.id == other_side["notification_id"]
        ).first()
        assert target.is_read == was_read, "他人の通知が既読にされた"
        assert target.user_id == owner_id
    finally:
        after.close()

    # 一覧にも他人の通知は出ない
    mine = store_a.get("/api/notifications", params={"limit": 500}).json()
    assert all(n["id"] != other_side["notification_id"] for n in mine)


def test_一般ユーザーは締め時間マスタを更新できない(store_a, vendor_a, other_side):
    payload = {
        "scope": "VENDOR", "vendor_id": 2, "rough_days_before": 1, "rough_time": "00:00",
        "final_days_before": 0, "final_time": "00:00",
        "reply_days_before": 0, "reply_time": "00:00",
    }
    for client in (store_a, vendor_a):
        assert client.post("/api/deadlines", json=payload).status_code == 403
        assert client.put(f"/api/deadlines/{other_side['deadline_id']}", json=payload).status_code == 403
        assert client.delete(f"/api/deadlines/{other_side['deadline_id']}").status_code == 403


def test_一般ユーザーはユーザーマスタを操作できない(store_a, vendor_a):
    for client in (store_a, vendor_a):
        assert client.get("/api/users").status_code == 403
        assert client.post("/api/users", json={
            "email": "hack@test.invalid", "name": "x", "password": "Passw0rd!!",
            "role_code": "ADMIN",
        }).status_code == 403
        assert client.put("/api/users/1", json={
            "email": "hack@test.invalid", "name": "x", "role_code": "ADMIN",
        }).status_code == 403
        assert client.delete("/api/users/1").status_code == 403
        assert client.post("/api/users/1/unlock").status_code == 403


def test_存在しないIDは404で情報を漏らさない(hq):
    for path in ("/api/orders/999999", "/api/products/999999"):
        res = hq.get(path)
        assert res.status_code == 404
        assert "見つかりません" in res.json()["detail"]


def test_本部は両方のデータへ到達できる(hq, other_side):
    """分離が効きすぎて本部の業務が回らなくなっていないことも確認する。"""
    assert hq.get(f"/api/orders/{other_side['order_id']}").status_code == 200
    assert hq.get(f"/api/products/{other_side['product_id']}").status_code == 200
    rows = hq.get("/api/change-requests", params={"limit": 500}).json()
    assert any(r["id"] == other_side["cr_id"] for r in rows)
    assert hq.post(
        f"/api/vendor/responses/{other_side['response_id']}/substitute-decision",
        json={"approve": True},
    ).status_code == 200
