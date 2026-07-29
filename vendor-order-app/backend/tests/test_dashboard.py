"""ダッシュボード集計のテスト。

本部が対応要否を判断する数字なので、スコープの適用と件数の正しさを検証する。
"""
from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import Order, utcnow

from .conftest import create_order, force_deadline_passed, future_date, get_products


def _dashboard(client, **params):
    res = client.get("/api/dashboard", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def test_ダッシュボードは全項目を返す(hq):
    data = _dashboard(hq)
    for key in (
        "today_deadline_count", "unconfirmed_count", "vendor_pending_count",
        "shortage_count", "partial_count", "substitute_count",
        "change_request_count", "reply_overdue_count",
    ):
        assert key in data, f"{key} が返っていない"
        assert isinstance(data[key], int)
        assert data[key] >= 0


def test_未確定件数は下書きの発注を数える(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    before = _dashboard(hq)["unconfirmed_count"]
    create_order(store_a, [products[0]["id"]], delivery_date=future_date(110))
    create_order(store_a, [products[1]["id"]], delivery_date=future_date(111))
    assert _dashboard(hq)["unconfirmed_count"] == before + 2


def test_ベンダー未確認件数は明細単位で数える(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    before = _dashboard(hq)["vendor_pending_count"]
    create_order(
        store_a, [products[0]["id"], products[1]["id"]],
        confirm=True, delivery_date=future_date(112),
    )
    assert _dashboard(hq)["vendor_pending_count"] == before + 2


def test_欠品と一部納品の件数が回答に追随する(store_a, vendor_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"], products[1]["id"]],
        confirm=True, qty_case=4, delivery_date=future_date(113),
    )[0]
    items = store_a.get(f"/api/orders/{order['id']}").json()["items"]
    before = _dashboard(hq)

    vendor_a.post("/api/vendor/responses", json={
        "order_item_id": items[0]["id"], "response_type": "SHORTAGE",
        "shortage_reason": "生産遅延",
    })
    vendor_a.post("/api/vendor/responses", json={
        "order_item_id": items[1]["id"], "response_type": "PARTIAL",
        "deliverable_qty": 2, "reason": "生産遅延",
    })

    after = _dashboard(hq)
    assert after["shortage_count"] == before["shortage_count"] + 1
    assert after["partial_count"] == before["partial_count"] + 1


def test_変更申請件数は申請中のみ数える(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(114)
    )[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    before = _dashboard(hq)["change_request_count"]
    cr = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 5, "requested_loose": 0, "reason": "監査",
    }).json()
    assert _dashboard(hq)["change_request_count"] == before + 1

    # 承認したら「申請中」から外れる
    hq.post(f"/api/change-requests/{cr['id']}/decision", json={"approve": True})
    assert _dashboard(hq)["change_request_count"] == before


def test_回答期限超過を数える(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(115)
    )[0]
    before = _dashboard(hq)["reply_overdue_count"]

    db = SessionLocal()
    try:
        row = db.query(Order).filter(Order.id == order["id"]).first()
        row.reply_deadline_at = utcnow() - timedelta(hours=3)
        db.add(row)
        db.commit()
    finally:
        db.close()

    assert _dashboard(hq)["reply_overdue_count"] == before + 1


def test_本日締め件数は日本時間の当日で数える(store_a, hq):
    """UTCで判定すると日本時間の夜間に日付がずれるため、JST基準であることを確認する。"""
    from datetime import datetime, time, timezone

    from app.config import APP_TZ
    from app.deadlines import jst_to_utc

    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(116)
    )[0]
    before = _dashboard(hq)["today_deadline_count"]

    # 日本時間の「今日」の 23:30 に締めを設定する（UTCでは翌日になる時刻）
    today_jst = datetime.now(timezone.utc).astimezone(APP_TZ).date()
    db = SessionLocal()
    try:
        row = db.query(Order).filter(Order.id == order["id"]).first()
        row.deadline_at = jst_to_utc(today_jst, time(23, 30))
        db.add(row)
        db.commit()
    finally:
        db.close()

    assert _dashboard(hq)["today_deadline_count"] == before + 1, \
        "日本時間の当日締めが数えられていない"


def test_ダッシュボードは店舗スコープで絞られる(store_a, store_b, hq):
    products_a = get_products(store_a, "テストベンダーA")
    create_order(store_a, [products_a[0]["id"]], delivery_date=future_date(117))

    store_a_view = _dashboard(store_a)
    store_b_view = _dashboard(store_b)
    hq_view = _dashboard(hq)

    assert store_a_view["store_id"] == 1
    assert store_b_view["store_id"] == 2
    assert hq_view["store_id"] is None
    # 本部の件数は各店舗の件数以上になる
    assert hq_view["unconfirmed_count"] >= store_a_view["unconfirmed_count"]
    assert hq_view["unconfirmed_count"] >= store_b_view["unconfirmed_count"]


def test_ダッシュボードはベンダースコープで絞られる(vendor_a, vendor_b, hq):
    a_view = _dashboard(vendor_a)
    b_view = _dashboard(vendor_b)
    hq_view = _dashboard(hq)

    assert a_view["vendor_id"] == 1
    assert b_view["vendor_id"] == 2
    assert hq_view["vendor_id"] is None
    assert hq_view["vendor_pending_count"] >= a_view["vendor_pending_count"]

    # ベンダーは未確定（下書き）の発注を数に含めない
    assert a_view["unconfirmed_count"] == 0


def test_他店舗他ベンダーを指定したダッシュボードは拒否される(store_a, vendor_a):
    assert store_a.get("/api/dashboard", params={"store_id": 2}).status_code == 403
    assert vendor_a.get("/api/dashboard", params={"vendor_id": 2}).status_code == 403


def test_納品日で絞り込める(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    delivery = future_date(118)
    create_order(store_a, [products[0]["id"]], delivery_date=delivery)

    filtered = _dashboard(hq, delivery_date=delivery)
    assert filtered["delivery_date"] == delivery
    assert filtered["unconfirmed_count"] >= 1
    assert filtered["unconfirmed_count"] <= _dashboard(hq)["unconfirmed_count"]
