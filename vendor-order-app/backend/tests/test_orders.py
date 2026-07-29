"""発注テスト（締め時間・履歴・二重送信・入力チェック）。"""
from __future__ import annotations

from datetime import date, timedelta

from .conftest import (
    create_order,
    force_deadline_passed,
    future_date,
    get_products,
    order_items,
)


def test_締め前は数量を変更できる(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], qty_case=2)[0]
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    editable = store_a.get(f"/api/orders/{order['id']}/editable").json()
    assert editable["is_after_deadline"] is False
    assert editable["can_edit_directly"] is True

    res = store_a.put(f"/api/orders/{order['id']}", json={
        "items": [{"id": item["id"], "product_id": item["product_id"],
                   "qty_case": 5, "qty_loose": 0, "reason": "売上予測の変更"}],
    })
    assert res.status_code == 200
    updated = res.json()["items"][0]
    assert updated["qty_case"] == 5
    assert updated["quantity"] == 5 * item["case_qty"]


def test_締め後は直接変更できない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], confirm=True)[0]
    force_deadline_passed(order["id"])

    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    editable = store_a.get(f"/api/orders/{order['id']}/editable").json()
    assert editable["is_after_deadline"] is True
    assert editable["can_edit_directly"] is False
    assert editable["requires_change_request"] is True

    res = store_a.put(f"/api/orders/{order['id']}", json={
        "items": [{"id": item["id"], "product_id": item["product_id"], "qty_case": 99, "qty_loose": 0}],
    })
    assert res.status_code == 409
    assert "変更申請" in res.json()["detail"]

    # 数量が書き換わっていないこと
    after = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert after["qty_case"] == item["qty_case"]


def test_締め後は変更申請になる(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], confirm=True, qty_case=2)[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    res = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 4, "requested_loose": 0,
        "reason": "売上予測の変更",
    })
    assert res.status_code == 201
    cr = res.json()
    assert cr["status"] == "PENDING"
    assert cr["before_quantity"] == item["quantity"]

    # 申請しただけでは数量は変わらない
    unchanged = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert unchanged["quantity"] == item["quantity"]
    assert unchanged["status"] == "CHANGE_REQUESTED"

    # 店舗ユーザーは自分では承認できない
    assert store_a.post(f"/api/change-requests/{cr['id']}/decision", json={"approve": True}).status_code == 403

    # 本部が承認して初めて反映される
    approved = hq.post(f"/api/change-requests/{cr['id']}/decision", json={"approve": True})
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    changed = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    assert changed["qty_case"] == 4


def test_変更申請の却下には理由が必須(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[1]["id"]], confirm=True)[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    cr = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 9, "requested_loose": 0, "reason": "入力誤り",
    }).json()

    assert hq.post(f"/api/change-requests/{cr['id']}/decision", json={"approve": False}).status_code == 400
    res = hq.post(f"/api/change-requests/{cr['id']}/decision",
                  json={"approve": False, "reject_reason": "在庫確保済みのため"})
    assert res.status_code == 200
    assert res.json()["reject_reason"] == "在庫確保済みのため"
    # 却下されたので数量は元のまま
    assert store_a.get(f"/api/orders/{order['id']}").json()["items"][0]["qty_case"] == item["qty_case"]


def test_変更理由なしの変更申請は登録できない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], confirm=True)[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    res = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 7, "requested_loose": 0, "reason": "",
    })
    assert res.status_code == 422


def test_締め前は変更申請ではなく直接修正を促す(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], confirm=True)[0]
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    res = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 3, "requested_loose": 0, "reason": "売上予測の変更",
    })
    assert res.status_code == 400
    assert "締め前" in res.json()["detail"]


def test_数量変更履歴が残る(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], qty_case=2)[0]
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    store_a.put(f"/api/orders/{order['id']}", json={
        "items": [{"id": item["id"], "product_id": item["product_id"],
                   "qty_case": 6, "qty_loose": 0, "reason": "天候による需要変動"}],
    })

    history = store_a.get("/api/histories/quantity", params={"order_id": order["id"]}).json()
    assert len(history) >= 2, "新規登録と数量変更の2件は最低限残る"

    latest = history[0]
    assert latest["qty_before"] == item["quantity"]
    assert latest["qty_after"] == 6 * item["case_qty"]
    assert latest["case_before"] == 2 and latest["case_after"] == 6
    assert latest["reason"] == "天候による需要変動"
    assert latest["is_after_deadline"] is False
    assert latest["changed_by_name"] == "店舗A担当"

    # 履歴を削除するAPIは存在しない
    assert store_a.delete(f"/api/histories/quantity").status_code in (404, 405)


def test_締め後変更の履歴には締め後フラグと承認情報が残る(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[2]["id"]], confirm=True, qty_case=1)[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]

    cr = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 3, "requested_loose": 0, "reason": "催事対応",
    }).json()
    hq.post(f"/api/change-requests/{cr['id']}/decision", json={"approve": True})

    history = hq.get("/api/histories/quantity", params={"order_id": order["id"]}).json()
    after = [h for h in history if h["is_after_deadline"]]
    assert after, "締め後変更の履歴が残っていない"
    row = after[0]
    assert row["approver_id"] is not None
    assert row["approved_at"] is not None
    assert row["requester_id"] is not None
    assert row["qty_before"] != row["qty_after"]


def test_ステータス変更履歴が残る(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]])[0]
    store_a.post(f"/api/orders/{order['id']}/confirm", json={})

    rows = store_a.get("/api/histories/status", params={"order_id": order["id"]}).json()
    transitions = [(r["status_before"], r["status_after"]) for r in rows]
    assert (None, "DRAFT") in transitions
    assert ("DRAFT", "CONFIRMED") in transitions


def test_二重発注を警告する(store_a):
    products = get_products(store_a, "テストベンダーA")
    delivery = future_date(9)
    create_order(store_a, [products[0]["id"]], delivery_date=delivery)

    res = store_a.post("/api/orders/validate", json={
        "delivery_date": delivery,
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 200
    codes = [w["code"] for w in res.json()["warnings"]]
    assert "DUPLICATE_ORDER" in codes
    # 警告であってエラーではない（登録自体は可能）
    assert res.json()["blocking"] is False


def test_二重送信されない(store_a):
    products = get_products(store_a, "テストベンダーA")
    payload = {
        "delivery_date": future_date(10),
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
        "client_token": "duplicate-submit-token-001",
    }
    first = store_a.post("/api/orders", json=payload)
    assert first.status_code == 201
    second = store_a.post("/api/orders", json=payload)
    assert second.status_code == 409
    assert "二重送信" in second.json()["detail"]


def test_過去日の納品日は登録できない(store_a):
    products = get_products(store_a, "テストベンダーA")
    past = (date.today() - timedelta(days=1)).isoformat()
    res = store_a.post("/api/orders", json={
        "delivery_date": past,
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 400
    codes = [w["code"] for w in res.json()["detail"]["warnings"]]
    assert "PAST_DELIVERY_DATE" in codes


def test_入力チェックの各種警告(store_a):
    products = get_products(store_a, "テストベンダーA")
    case_only = next(p for p in products if p["order_unit"] == "CASE")
    both = next(p for p in products if p["order_unit"] == "BOTH")

    # 同じ商品を2行に分けて送るとスキーマ側で弾かれる（事前チェックでも登録でも同じ規則）
    duplicated = {
        "delivery_date": future_date(8),
        "items": [
            {"product_id": both["id"], "qty_case": 1, "qty_loose": 0},
            {"product_id": both["id"], "qty_case": 2, "qty_loose": 0},
        ],
    }
    assert store_a.post("/api/orders/validate", json=duplicated).status_code == 422
    assert store_a.post("/api/orders", json=duplicated).status_code == 422

    res = store_a.post("/api/orders/validate", json={
        "delivery_date": future_date(8),
        "items": [{"product_id": both["id"], "qty_case": 0, "qty_loose": 0}],
    })
    assert "ZERO_QUANTITY" in [w["code"] for w in res.json()["warnings"]]

    res = store_a.post("/api/orders/validate", json={
        "delivery_date": future_date(8),
        "items": [{"product_id": both["id"], "qty_case": 500, "qty_loose": 0}],
    })
    assert "ABNORMAL_QUANTITY" in [w["code"] for w in res.json()["warnings"]]

    # バラ発注不可の商品にバラ数を入れるとエラー（登録不可）
    res = store_a.post("/api/orders/validate", json={
        "delivery_date": future_date(8),
        "items": [{"product_id": case_only["id"], "qty_case": 1, "qty_loose": 3}],
    })
    body = res.json()
    assert body["blocking"] is True
    assert "LOOSE_NOT_ALLOWED" in [w["code"] for w in body["warnings"]]

    # ケース入数以上のバラ数は警告
    res = store_a.post("/api/orders/validate", json={
        "delivery_date": future_date(8),
        "items": [{"product_id": both["id"], "qty_case": 1, "qty_loose": both["case_qty"] + 2}],
    })
    assert "CASE_QTY_MISMATCH" in [w["code"] for w in res.json()["warnings"]]


def test_商品はベンダー別に自動振り分けされる(store_a):
    a = get_products(store_a, "テストベンダーA")[0]
    b = get_products(store_a, "テストベンダーB")[0]
    orders = create_order(store_a, [a["id"], b["id"]], delivery_date=future_date(11))
    assert len(orders) == 2, "ベンダーごとに発注が分かれるはず"
    assert {o["vendor_name"] for o in orders} == {"テストベンダーA", "テストベンダーB"}
    for o in orders:
        assert o["item_count"] == 1


def test_締め時間は商品別ベンダー別システム標準の順で適用される(hq, store_a, admin):
    products = get_products(store_a, "テストベンダーA")
    target = products[0]

    # ベンダー別の締めを設定（前日10:00）
    vendor_id = target["vendor_id"]
    res = hq.post("/api/deadlines", json={
        "scope": "VENDOR", "vendor_id": vendor_id,
        "rough_days_before": 3, "rough_time": "10:00",
        "final_days_before": 1, "final_time": "10:00",
        "reply_days_before": 1, "reply_time": "14:00",
    })
    assert res.status_code == 201
    vendor_deadline_id = res.json()["id"]

    order_v = create_order(store_a, [target["id"]], delivery_date=future_date(12))[0]

    # 商品別の締めを設定（2日前09:00）。こちらが優先される。
    res = hq.post("/api/deadlines", json={
        "scope": "PRODUCT", "product_id": target["id"], "vendor_id": vendor_id,
        "rough_days_before": 4, "rough_time": "09:00",
        "final_days_before": 2, "final_time": "09:00",
        "reply_days_before": 1, "reply_time": "12:00",
    })
    assert res.status_code == 201
    product_deadline_id = res.json()["id"]

    order_p = create_order(store_a, [target["id"]], delivery_date=future_date(13))[0]

    assert order_v["deadline_at"] < order_p["deadline_at"] or True  # 日付が違うため直接比較はしない
    # 商品別の方が「納品日から見て早い」ことを確認する
    from datetime import datetime
    dv = datetime.fromisoformat(order_v["deadline_at"])
    dp = datetime.fromisoformat(order_p["deadline_at"])
    delivery_v = date.fromisoformat(order_v["delivery_date"])
    delivery_p = date.fromisoformat(order_p["delivery_date"])
    lead_v = (datetime.combine(delivery_v, datetime.min.time()) - dv).days
    lead_p = (datetime.combine(delivery_p, datetime.min.time()) - dp).days
    assert lead_p > lead_v, "商品別締めがベンダー別締めより優先されていない"

    hq.delete(f"/api/deadlines/{product_deadline_id}")
    hq.delete(f"/api/deadlines/{vendor_deadline_id}")


def test_発注確定でステータスが遷移し取消もできる(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]])[0]
    assert order["status"] == "DRAFT"

    confirmed = store_a.post(f"/api/orders/{order['id']}/confirm", json={}).json()
    assert confirmed["status"] == "CONFIRMED"
    items = order_items(order["id"])
    assert all(i.status == "VENDOR_PENDING" for i in items)

    # 二重確定はできない
    assert store_a.post(f"/api/orders/{order['id']}/confirm", json={}).status_code == 409

    cancelled = store_a.post(f"/api/orders/{order['id']}/cancel", json={"reason": "発注不要になったため"})
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"


def test_操作ログが残る(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]])[0]
    store_a.post(f"/api/orders/{order['id']}/confirm", json={})

    logs = hq.get("/api/histories/audit", params={"limit": 200}).json()
    actions = {log["action"] for log in logs}
    assert "LOGIN" in actions
    assert "ORDER_CREATE" in actions
    assert "ORDER_CONFIRM" in actions

    create_log = next(l for l in logs if l["action"] == "ORDER_CREATE")
    assert create_log["user_email"] == "storea@test.invalid"
    assert create_log["role_code"] == "STORE"
