"""ベンダー回答テスト。"""
from __future__ import annotations

from .conftest import create_order, future_date, get_products


def _confirmed_item(store_client, vendor_name, offset=20):
    products = get_products(store_client, vendor_name)
    order = create_order(
        store_client, [products[0]["id"]], confirm=True, qty_case=4,
        delivery_date=future_date(offset),
    )[0]
    detail = store_client.get(f"/api/orders/{order['id']}").json()
    return order, detail["items"][0]


def test_自社発注のみ回答できる(store_a, vendor_a, vendor_b):
    order, item = _confirmed_item(store_a, "テストベンダーA", 21)

    # 他社ベンダーは回答できない
    res = vendor_b.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "FULL",
    })
    assert res.status_code == 403

    # 自社ベンダーは回答できる
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "FULL",
    })
    assert res.status_code == 201
    assert res.json()["response_type"] == "FULL"
    assert res.json()["deliverable_qty"] == item["quantity"]


def test_店舗と本部はベンダー回答を作成できない(store_a, hq):
    order, item = _confirmed_item(store_a, "テストベンダーA", 22)
    for client in (store_a, hq):
        res = client.post("/api/vendor/responses", json={
            "order_item_id": item["id"], "response_type": "FULL",
        })
        assert res.status_code == 403


def test_一部納品時に数量と理由が必須(store_a, vendor_a):
    order, item = _confirmed_item(store_a, "テストベンダーA", 23)

    # 数量なし
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL", "reason": "生産遅延",
    })
    assert res.status_code == 400
    assert "納品可能数量" in res.json()["detail"]

    # 理由なし
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL", "deliverable_qty": 3,
    })
    assert res.status_code == 400
    assert "理由" in res.json()["detail"]

    # 発注数量以上は一部納品にならない
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL",
        "deliverable_qty": item["quantity"], "reason": "生産遅延",
    })
    assert res.status_code == 400

    # 正常
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL",
        "deliverable_qty": 3, "reason": "生産遅延のため",
    })
    assert res.status_code == 201
    body = res.json()
    assert body["deliverable_qty"] == 3
    assert body["shortage_qty"] == item["quantity"] - 3

    updated = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert updated["status"] == "PARTIAL"
    assert updated["confirmed_quantity"] == 3


def test_欠品時に理由が必須(store_a, vendor_a):
    order, item = _confirmed_item(store_a, "テストベンダーA", 24)

    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE",
    })
    assert res.status_code == 400
    assert "欠品理由" in res.json()["detail"]

    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE",
        "shortage_reason": "原材料不足のため", "next_available_date": future_date(30),
    })
    assert res.status_code == 201
    assert res.json()["shortage_qty"] == item["quantity"]
    assert res.json()["deliverable_qty"] == 0

    updated = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert updated["status"] == "SHORTAGE"
    assert updated["confirmed_quantity"] == 0


def test_代替商品提案は本部承認後に確定する(store_a, vendor_a, hq):
    order, item = _confirmed_item(store_a, "テストベンダーA", 25)

    # 代替商品名なしはエラー
    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE", "sub_deliverable_qty": 5,
    })
    assert res.status_code == 400

    res = vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SUBSTITUTE",
        "sub_product_name": "代替テスト商品", "sub_jan_code": "0200000009999",
        "sub_deliverable_qty": 5, "sub_cost": 120.0, "sub_delivery_date": future_date(26),
        "sub_comment": "同等品でのご提案です",
    })
    assert res.status_code == 201
    response_id = res.json()["id"]
    assert res.json()["sub_approved_at"] is None

    updated = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert updated["status"] == "SUBSTITUTE"

    # ベンダー自身は承認できない
    assert vendor_a.post(f"/api/vendor/responses/{response_id}/substitute-decision",
                         json={"approve": True}).status_code == 403
    # 店舗も承認できない
    assert store_a.post(f"/api/vendor/responses/{response_id}/substitute-decision",
                        json={"approve": True}).status_code == 403

    # 本部が承認して確定
    res = hq.post(f"/api/vendor/responses/{response_id}/substitute-decision", json={"approve": True})
    assert res.status_code == 200
    assert res.json()["sub_approved_at"] is not None

    # 二重判定はできない
    assert hq.post(f"/api/vendor/responses/{response_id}/substitute-decision",
                   json={"approve": True}).status_code == 409


def test_回答履歴が残る(store_a, vendor_a):
    order, item = _confirmed_item(store_a, "テストベンダーA", 27)

    vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "PARTIAL",
        "deliverable_qty": 2, "reason": "初回回答",
    })
    vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "FULL",
    })

    rows = vendor_a.get("/api/vendor/responses", params={"order_item_id": item["id"]}).json()
    assert len(rows) == 2, "訂正しても前の回答が消えてはいけない"
    latest = [r for r in rows if r["is_latest"]]
    assert len(latest) == 1
    assert latest[0]["response_type"] == "FULL"
    # 古い回答も内容ごと残っている
    old = [r for r in rows if not r["is_latest"]][0]
    assert old["reason"] == "初回回答"


def test_受注確認でステータスが変わる(store_a, vendor_a):
    order, item = _confirmed_item(store_a, "テストベンダーA", 28)
    assert item["status"] == "VENDOR_PENDING"

    res = vendor_a.post("/api/vendor/ack", json={"order_id": order["id"]})
    assert res.status_code == 200
    assert res.json()["updated_items"] >= 1

    updated = store_a.get(f"/api/orders/{order['id']}").json()
    assert updated["items"][0]["status"] == "VENDOR_ACK"
    assert updated["status"] == "VENDOR_ACK"


def test_未確定の発注はベンダーから見えない(store_a, vendor_a):
    products = get_products(store_a, "テストベンダーA")
    draft = create_order(store_a, [products[0]["id"]], confirm=False, delivery_date=future_date(29))[0]

    assert vendor_a.get(f"/api/orders/{draft['id']}").status_code == 403
    visible_ids = {o["id"] for o in vendor_a.get("/api/orders").json()}
    assert draft["id"] not in visible_ids

    # 確定するとベンダーから見えるようになる
    store_a.post(f"/api/orders/{draft['id']}/confirm", json={})
    assert vendor_a.get(f"/api/orders/{draft['id']}").status_code == 200


def test_ベンダー集計は自社分のみ(store_a, vendor_a, hq):
    a = get_products(store_a, "テストベンダーA")[0]
    b = get_products(store_a, "テストベンダーB")[0]
    create_order(store_a, [a["id"], b["id"]], confirm=True, delivery_date=future_date(31))

    rows = vendor_a.get("/api/vendor/summary/by-product", params={"delivery_date": future_date(31)}).json()
    names = {r["product_name"] for r in rows}
    assert a["name"] in names
    assert b["name"] not in names

    # 本部は両方見える
    hq_rows = hq.get("/api/vendor/summary/by-product", params={"delivery_date": future_date(31)}).json()
    hq_names = {r["product_name"] for r in hq_rows}
    assert {a["name"], b["name"]} <= hq_names


def test_操作ログにベンダー回答が記録される(store_a, vendor_a, hq):
    order, item = _confirmed_item(store_a, "テストベンダーA", 32)
    vendor_a.post("/api/vendor/responses", json={
        "order_item_id": item["id"], "response_type": "SHORTAGE", "shortage_reason": "生産遅延",
    })
    logs = hq.get("/api/histories/audit", params={"action": "VENDOR_SHORTAGE"}).json()
    assert logs
    assert logs[0]["role_code"] == "VENDOR"
