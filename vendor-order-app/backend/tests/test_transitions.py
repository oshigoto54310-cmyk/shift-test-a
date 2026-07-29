"""ステータス遷移ガードの回帰テスト。

第三者監査で、ベンダーが「全数納品」と回答して納品確定になった後でも、
締め前であれば店舗が数量を書き換えられ、取消までできてしまうことが判明した。
回答の前提が崩れるため、その再発防止として追加した。
"""
from __future__ import annotations

import pytest

from .conftest import create_order, future_date, get_products


def _answered_order(store_client, vendor_client, response_type: str, offset: int, **extra):
    """ベンダーが回答済みの発注を作る（締め前のまま）。"""
    products = get_products(store_client, "テストベンダーA")
    order = create_order(
        store_client, [products[0]["id"]], confirm=True, qty_case=4,
        delivery_date=future_date(offset),
    )[0]
    item = store_client.get(f"/api/orders/{order['id']}").json()["items"][0]
    vendor_client.post("/api/vendor/ack", json={"order_id": order["id"]})
    body = {"order_item_id": item["id"], "response_type": response_type}
    body.update(extra)
    res = vendor_client.post("/api/vendor/responses", json=body)
    assert res.status_code == 201, res.text
    return order, item


def _put(client, order_id, item, version, qty=99):
    return client.put(f"/api/orders/{order_id}", json={
        "version": version,
        "items": [{"id": item["id"], "product_id": item["product_id"],
                   "qty_case": qty, "qty_loose": 0}],
    })


def test_納品確定後は締め前でも数量を変更できない(store_a, vendor_a):
    order, item = _answered_order(store_a, vendor_a, "FULL", 60)
    view = store_a.get(f"/api/orders/{order['id']}").json()
    assert view["status"] == "DELIVERED"
    assert view["is_after_deadline"] is False, "締め前であることを前提としたテスト"

    res = _put(store_a, order["id"], item, view["version"])
    assert res.status_code == 409
    assert "直接変更できません" in res.json()["detail"]

    # 数量が書き換わっていないこと
    after = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert after["qty_case"] == item["qty_case"]


def test_納品確定後は店舗から取消できない(store_a, vendor_a):
    order, _ = _answered_order(store_a, vendor_a, "FULL", 61)
    res = store_a.post(f"/api/orders/{order['id']}/cancel", json={"reason": "監査"})
    assert res.status_code == 409
    assert "取消できません" in res.json()["detail"]
    assert store_a.get(f"/api/orders/{order['id']}").json()["status"] == "DELIVERED"


@pytest.mark.parametrize(
    "response_type,extra,expected_status",
    [
        ("PARTIAL", {"deliverable_qty": 2, "reason": "生産遅延"}, "PARTIAL"),
        ("SHORTAGE", {"shortage_reason": "原材料不足"}, "SHORTAGE"),
        ("SUBSTITUTE", {"sub_product_name": "代替品", "sub_deliverable_qty": 2}, "SUBSTITUTE"),
    ],
)
def test_ベンダー回答済みの明細は直接編集できない(
    store_a, vendor_a, response_type, extra, expected_status
):
    offset = {"PARTIAL": 62, "SHORTAGE": 63, "SUBSTITUTE": 64}[response_type]
    order, item = _answered_order(store_a, vendor_a, response_type, offset, **extra)
    view = store_a.get(f"/api/orders/{order['id']}").json()
    assert view["status"] == expected_status

    res = _put(store_a, order["id"], item, view["version"])
    assert res.status_code == 409, f"{response_type} 後に直接編集できてしまう"


def test_ベンダー未確認までは締め前なら編集できる(store_a, vendor_a):
    """回答前（発注確定・ベンダー未確認・ベンダー確認済み）は編集を許す。"""
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(65)
    )[0]
    view = store_a.get(f"/api/orders/{order['id']}").json()
    item = view["items"][0]
    assert view["status"] == "CONFIRMED"

    res = _put(store_a, order["id"], item, view["version"], qty=6)
    assert res.status_code == 200

    # ベンダーが受注確認しただけの状態でも編集できる
    vendor_a.post("/api/vendor/ack", json={"order_id": order["id"]})
    view2 = store_a.get(f"/api/orders/{order['id']}").json()
    assert view2["status"] == "VENDOR_ACK"
    res = _put(store_a, order["id"], item, view2["version"], qty=7)
    assert res.status_code == 200
    assert store_a.get(f"/api/orders/{order['id']}").json()["items"][0]["qty_case"] == 7


def test_取消済みの発注は変更も再取消もできない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(66))[0]
    view = store_a.get(f"/api/orders/{order['id']}").json()
    item = view["items"][0]

    assert store_a.post(f"/api/orders/{order['id']}/cancel", json={"reason": "監査"}).status_code == 200
    after = store_a.get(f"/api/orders/{order['id']}").json()
    assert after["status"] == "CANCELLED"

    assert _put(store_a, order["id"], item, after["version"]).status_code == 409
    assert store_a.post(f"/api/orders/{order['id']}/cancel", json={"reason": "再"}).status_code == 409
    assert store_a.post(f"/api/orders/{order['id']}/confirm", json={}).status_code == 409


def test_確定済みの発注は再確定できない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(67))[0]
    assert store_a.post(f"/api/orders/{order['id']}/confirm", json={}).status_code == 200
    assert store_a.post(f"/api/orders/{order['id']}/confirm", json={}).status_code == 409


def test_編集可否APIが遷移ガードを反映する(store_a, vendor_a):
    order, _ = _answered_order(store_a, vendor_a, "SHORTAGE", 68, shortage_reason="生産遅延")
    editable = store_a.get(f"/api/orders/{order['id']}/editable").json()
    assert editable["is_after_deadline"] is False
    assert editable["can_edit_directly"] is False, "画面側に編集不可を伝えられていない"
