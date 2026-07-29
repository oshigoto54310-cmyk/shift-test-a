"""入力値・境界値の回帰テスト。

第三者監査で以下が受理されてしまうことが判明したため追加した。
- 代替提案で発注数量を超える納品可能数量
- 欠品回答の次回納品可能日に過去日
- 代替提案の原価に負の値
- 納品日に100年後の日付
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.config import APP_TZ
from app.deadlines import jst_to_utc, parse_hhmm, resolve_deadline, utc_to_jst
from app.database import SessionLocal
from app.services import compute_quantity

from .conftest import create_order, future_date, get_products


def _confirmed_item(store_client, vendor_client, offset: int, qty_case: int = 3):
    products = get_products(store_client, "テストベンダーA")
    order = create_order(
        store_client, [products[0]["id"]], confirm=True, qty_case=qty_case,
        delivery_date=future_date(offset),
    )[0]
    item = store_client.get(f"/api/orders/{order['id']}").json()["items"][0]
    vendor_client.post("/api/vendor/ack", json={"order_id": order["id"]})
    return order, item


# --------------------------------------------------------------------------
# ベンダー回答の境界値
# --------------------------------------------------------------------------
def test_代替提案は発注数量を超える数量を受け付けない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 70)
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "代替品", "sub_deliverable_qty": item["quantity"] + 1,
    })
    assert res.status_code == 400
    assert "超えています" in res.json()["detail"]

    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "代替品", "sub_deliverable_qty": 1,
        "deliverable_qty": item["quantity"] + 100,
    })
    assert res.status_code == 400


def test_欠品の次回納品可能日に過去日は指定できない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 71)
    past = (date.today() - timedelta(days=1)).isoformat()
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE",
        "shortage_reason": "原材料不足", "next_available_date": past,
    })
    assert res.status_code == 400
    assert "過去の日付" in res.json()["detail"]

    # 今日以降なら受理される
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE",
        "shortage_reason": "原材料不足", "next_available_date": future_date(80),
    })
    assert res.status_code == 201


def test_代替商品の納品可能日に過去日は指定できない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 72)
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "代替品", "sub_deliverable_qty": 1,
        "sub_delivery_date": (date.today() - timedelta(days=3)).isoformat(),
    })
    assert res.status_code == 400


def test_代替提案の原価に負の値は指定できない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 73)
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "代替品", "sub_deliverable_qty": 1, "sub_cost": -100,
    })
    assert res.status_code == 422


def test_一部納品の数量は0や発注数量以上を受け付けない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 74)
    for qty in (0, item["quantity"], item["quantity"] + 5):
        res = vendor_a.post("/api/vendor/responses", json={
            "order_item_id": item["id"], "response_type": "PARTIAL",
            "deliverable_qty": qty, "reason": "生産遅延",
        })
        assert res.status_code == 400, f"納品可能数量 {qty} が受理された"

    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL",
        "deliverable_qty": -1, "reason": "生産遅延",
    })
    assert res.status_code == 422


def test_空白のみの理由は受け付けない(store_a, vendor_a):
    order, item = _confirmed_item(store_a, vendor_a, 75)
    assert vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL",
        "deliverable_qty": 1, "reason": "   ",
    }).status_code == 400
    assert vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE", "shortage_reason": "  ",
    }).status_code == 400


# --------------------------------------------------------------------------
# 発注入力の境界値
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "qty_case,qty_loose,expected",
    [(-1, 0, 422), (0, -1, 422), (10**9, 0, 422), (0, 10**9, 422)],
)
def test_数量の範囲外は受け付けない(store_a, qty_case, qty_loose, expected):
    products = get_products(store_a, "テストベンダーA")
    res = store_a.post("/api/orders", json={
        "delivery_date": future_date(76),
        "items": [{"product_id": products[0]["id"], "qty_case": qty_case, "qty_loose": qty_loose}],
    })
    assert res.status_code == expected


def test_小数の数量は受け付けない(store_a):
    products = get_products(store_a, "テストベンダーA")
    res = store_a.post("/api/orders", json={
        "delivery_date": future_date(77),
        "items": [{"product_id": products[0]["id"], "qty_case": 1.5, "qty_loose": 0}],
    })
    assert res.status_code == 422


def test_遠すぎる納品日は登録できない(store_a):
    products = get_products(store_a, "テストベンダーA")
    far = (date.today() + timedelta(days=400)).isoformat()
    res = store_a.post("/api/orders", json={
        "delivery_date": far,
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 400
    codes = [w["code"] for w in res.json()["detail"]["warnings"]]
    assert "DELIVERY_DATE_TOO_FAR" in codes

    # 1年以内なら登録できる
    ok = store_a.post("/api/orders", json={
        "delivery_date": (date.today() + timedelta(days=300)).isoformat(),
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert ok.status_code == 201


def test_明細が空の発注は登録できない(store_a):
    res = store_a.post("/api/orders", json={"delivery_date": future_date(78), "items": []})
    assert res.status_code == 422


def test_不正な日付形式は受け付けない(store_a):
    products = get_products(store_a, "テストベンダーA")
    for bad in ("9999-99-99", "not-a-date", ""):
        res = store_a.post("/api/orders", json={
            "delivery_date": bad,
            "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
        })
        assert res.status_code == 422, f"{bad} が受理された"


def test_他ベンダー商品を明示指定した発注は拒否される(store_a):
    a = get_products(store_a, "テストベンダーA")[0]
    b = get_products(store_a, "テストベンダーB")[0]
    res = store_a.post("/api/orders", json={
        "delivery_date": future_date(79),
        "vendor_id": a["vendor_id"],
        "items": [{"product_id": b["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 400


# --------------------------------------------------------------------------
# 数量計算・締め時間の境界
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "case_qty,qty_case,qty_loose,expected",
    [(10, 2, 3, 23), (1, 5, 0, 5), (12, 0, 7, 7), (10, 0, 0, 0), (0, 2, 1, 3)],
)
def test_数量計算(case_qty, qty_case, qty_loose, expected):
    """ケース入数が0でも1として扱い、0除算や0掛けにならないこと。"""
    assert compute_quantity(case_qty, qty_case, qty_loose) == expected


def test_締め時刻は日本時間で解決されUTCで保存される():
    """内部保存はUTC、業務判定は日本時間、という設計が守られていること。"""
    db = SessionLocal()
    try:
        delivery = date(2026, 8, 20)
        resolved = resolve_deadline(db, delivery_date=delivery, vendor_id=1)
        # システム標準は「前日12:00（日本時間）」
        jst = utc_to_jst(resolved.final_deadline_at)
        assert jst.date() == delivery - timedelta(days=1)
        assert (jst.hour, jst.minute) == (12, 0)
        # 保存値は naive（UTC想定）であること
        assert resolved.final_deadline_at.tzinfo is None
        # 日本時間の12:00 は UTC 03:00
        assert resolved.final_deadline_at.hour == 3
    finally:
        db.close()


@pytest.mark.parametrize(
    "delivery,expected_deadline_date",
    [
        (date(2026, 1, 1), date(2025, 12, 31)),   # 年をまたぐ
        (date(2026, 3, 1), date(2026, 2, 28)),    # 月末
        (date(2028, 3, 1), date(2028, 2, 29)),    # うるう年
    ],
)
def test_締め時刻の日付境界(delivery, expected_deadline_date):
    db = SessionLocal()
    try:
        resolved = resolve_deadline(db, delivery_date=delivery, vendor_id=1)
        assert utc_to_jst(resolved.final_deadline_at).date() == expected_deadline_date
    finally:
        db.close()


def test_不正な時刻文字列は既定値にフォールバックする():
    """マスタに壊れた値が入っていても落ちないこと。"""
    assert parse_hhmm("12:00").hour == 12
    assert parse_hhmm("あいうえお").hour == 12
    assert parse_hhmm("").hour == 12
    assert parse_hhmm(None).hour == 12


def test_日本時間とUTCの相互変換が一致する():
    from datetime import time

    jst_noon = jst_to_utc(date(2026, 7, 1), time(12, 0))
    assert jst_noon.hour == 3          # JST 12:00 = UTC 03:00
    assert utc_to_jst(jst_noon).hour == 12
    assert utc_to_jst(jst_noon).tzinfo == APP_TZ
