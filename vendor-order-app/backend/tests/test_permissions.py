"""権限テスト。

「画面に出さない」だけでは不十分で、サーバー側で取得できないことを確認する。
URL や API パラメータを書き換えても他社・他店舗のデータへ到達できないこと。
"""
from __future__ import annotations

import pytest

from .conftest import create_order, future_date, get_products, make_client


# --------------------------------------------------------------------------
# ベンダー間のデータ分離
# --------------------------------------------------------------------------
def test_ベンダーAはベンダーBのデータを取得できない(vendor_a, vendor_b, store_a):
    a_products = get_products(store_a, "テストベンダーA")
    b_products = get_products(store_a, "テストベンダーB")
    create_order(store_a, [a_products[0]["id"]], confirm=True)
    create_order(store_a, [b_products[0]["id"]], confirm=True)

    orders_a = vendor_a.get("/api/orders").json()
    assert orders_a, "ベンダーAの発注が1件も見えないのはおかしい"
    assert all(o["vendor_name"] == "テストベンダーA" for o in orders_a)

    orders_b = vendor_b.get("/api/orders").json()
    assert all(o["vendor_name"] == "テストベンダーB" for o in orders_b)

    # 商品もベンダーを跨いで見えない
    assert all(p["vendor_name"] == "テストベンダーA" for p in vendor_a.get("/api/products").json())
    # ベンダー一覧にも他社は出ない（＝切替UIを作れない）
    vendors = vendor_a.get("/api/vendors").json()
    assert [v["name"] for v in vendors] == ["テストベンダーA"]


def test_ベンダーAはURL変更でベンダーBの発注を開けない(vendor_a, vendor_b, store_a):
    b_products = get_products(store_a, "テストベンダーB")
    order = create_order(store_a, [b_products[0]["id"]], confirm=True)[0]

    # ベンダーBは開ける
    assert vendor_b.get(f"/api/orders/{order['id']}").status_code == 200
    # ベンダーAは 403
    res = vendor_a.get(f"/api/orders/{order['id']}")
    assert res.status_code == 403
    assert "他ベンダー" in res.json()["detail"]


def test_ベンダーAがAPIへvendor_idを指定しても他社データを取得できない(vendor_a, store_a):
    b_products = get_products(store_a, "テストベンダーB")
    create_order(store_a, [b_products[0]["id"]], confirm=True)

    # 明示的に他ベンダーを指定 → 403（黙って自社に読み替えない）
    assert vendor_a.get("/api/orders", params={"vendor_id": 2}).status_code == 403
    assert vendor_a.get("/api/products", params={"vendor_id": 2}).status_code == 403
    assert vendor_a.get("/api/dashboard", params={"vendor_id": 2}).status_code == 403
    assert vendor_a.get("/api/vendor/summary/by-product", params={"vendor_id": 2}).status_code == 403
    assert vendor_a.get("/api/exports/orders", params={"vendor_id": 2}).status_code == 403

    # 自社IDの明示指定は許可される
    me = vendor_a.get("/api/auth/me").json()
    assert vendor_a.get("/api/orders", params={"vendor_id": me["vendor_id"]}).status_code == 200


def test_ベンダーは他ベンダーの回答履歴を取得できない(vendor_a, vendor_b, store_a):
    b_products = get_products(store_a, "テストベンダーB")
    order = create_order(store_a, [b_products[0]["id"]], confirm=True)[0]
    detail = vendor_b.get(f"/api/orders/{order['id']}").json()
    item_id = detail["items"][0]["id"]
    vendor_b.post("/api/vendor/responses", json={"order_item_id": item_id, "response_type": "FULL"})

    rows_a = vendor_a.get("/api/vendor/responses").json()
    assert all(r["vendor_id"] != detail["vendor_id"] for r in rows_a)
    # 他社の明細IDを直接指定しても回答できない
    res = vendor_a.post("/api/vendor/responses", json={"order_item_id": item_id, "response_type": "FULL"})
    assert res.status_code == 403


# --------------------------------------------------------------------------
# 店舗間のデータ分離
# --------------------------------------------------------------------------
def test_店舗Aは店舗Bの発注を取得できない(store_a, store_b):
    products = get_products(store_b, "テストベンダーA")
    order_b = create_order(store_b, [products[0]["id"]], confirm=True)[0]

    assert store_b.get(f"/api/orders/{order_b['id']}").status_code == 200
    res = store_a.get(f"/api/orders/{order_b['id']}")
    assert res.status_code == 403
    assert "他店舗" in res.json()["detail"]

    # 一覧にも出ない
    assert all(o["store_name"] == "テスト店舗A" for o in store_a.get("/api/orders").json())


def test_店舗ユーザーはstore_idを指定しても他店舗を見られない(store_a):
    assert store_a.get("/api/orders", params={"store_id": 2}).status_code == 403
    assert store_a.get("/api/dashboard", params={"store_id": 2}).status_code == 403
    assert store_a.get("/api/exports/orders", params={"store_id": 2}).status_code == 403
    assert store_a.get("/api/favorites", params={"store_id": 2}).status_code == 403

    # 他店舗名義での発注登録もできない
    products = get_products(store_a)
    res = store_a.post("/api/orders", json={
        "store_id": 2, "delivery_date": future_date(),
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 403


def test_店舗ユーザーはベンダー切替できない(store_a):
    me = store_a.get("/api/auth/me").json()
    assert me["can_switch_vendor"] is False
    assert me["can_switch_store"] is False
    # 店舗一覧には自店舗しか返らない（切替UIを構成できない）
    stores = store_a.get("/api/stores").json()
    assert [s["name"] for s in stores] == ["テスト店舗A"]


def test_ベンダーユーザーはベンダー切替できない(vendor_a):
    me = vendor_a.get("/api/auth/me").json()
    assert me["can_switch_vendor"] is False
    assert me["can_switch_store"] is False
    assert len(vendor_a.get("/api/vendors").json()) == 1


def test_本部と管理者はベンダーと店舗を切り替えられる(hq, admin, store_a):
    for client in (hq, admin):
        me = client.get("/api/auth/me").json()
        assert me["can_switch_vendor"] is True
        assert me["can_switch_store"] is True
        assert len(client.get("/api/vendors").json()) == 2
        assert len(client.get("/api/stores").json()) == 2

    products = get_products(store_a, "テストベンダーA")
    create_order(store_a, [products[0]["id"]], confirm=True)

    all_orders = hq.get("/api/orders").json()
    filtered = hq.get("/api/orders", params={"vendor_id": 1}).json()
    assert len(filtered) <= len(all_orders)
    assert all(o["vendor_id"] == 1 for o in filtered)


# --------------------------------------------------------------------------
# 管理画面・ロール
# --------------------------------------------------------------------------
def test_一般ユーザーは管理画面へ入れない(store_a, vendor_a, hq, admin):
    for client in (store_a, vendor_a):
        assert client.get("/api/users").status_code == 403
        assert client.get("/api/roles").status_code == 403
        assert client.post("/api/stores", json={"code": "X", "name": "不正店舗"}).status_code == 403
        assert client.post("/api/vendors", json={"code": "X", "name": "不正ベンダー"}).status_code == 403
        assert client.get("/api/histories/audit").status_code == 403
        assert client.get("/api/histories/login").status_code == 403

    # 本部は操作ログを見られるがユーザー管理はできない
    assert hq.get("/api/histories/audit").status_code == 200
    assert hq.get("/api/users").status_code == 403
    # 管理者はどちらもできる
    assert admin.get("/api/users").status_code == 200
    assert admin.get("/api/histories/login").status_code == 200


def test_ベンダーユーザーは発注登録も確定もできない(vendor_a, store_a):
    products = get_products(store_a, "テストベンダーA")
    res = vendor_a.post("/api/orders", json={
        "delivery_date": future_date(),
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 403

    order = create_order(store_a, [products[0]["id"]])[0]
    assert vendor_a.post(f"/api/orders/{order['id']}/confirm", json={}).status_code == 403


def test_未ログインではAPIを利用できない(anon):
    for path in ["/api/orders", "/api/auth/me", "/api/products", "/api/dashboard", "/api/exports/orders"]:
        assert anon.get(path).status_code == 401


def test_停止されたアカウントはログインできない(admin):
    users = admin.get("/api/users").json()
    target = next(u for u in users if u["email"] == "locked@test.invalid")
    assert admin.delete(f"/api/users/{target['id']}").status_code == 200

    client = make_client()
    res = client.post("/api/auth/login", json={"email": "locked@test.invalid", "password": "TestPassword123!"})
    assert res.status_code in (401, 403)


def test_ログイン失敗が続くとロックされる():
    client = make_client()
    for _ in range(5):
        res = client.post("/api/auth/login", json={"email": "storeb@test.invalid", "password": "wrong-password"})
        assert res.status_code == 401
    # 正しいパスワードでもロック中は入れない
    res = client.post("/api/auth/login", json={"email": "storeb@test.invalid", "password": "TestPassword123!"})
    assert res.status_code == 423
    assert "ロック" in res.json()["detail"]


def test_CSRFトークンがないと更新操作は拒否される(store_a):
    products = get_products(store_a)
    client_without_csrf = make_client("storea@test.invalid")
    del client_without_csrf.headers["X-CSRF-Token"]
    res = client_without_csrf.post("/api/orders", json={
        "delivery_date": future_date(),
        "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
    })
    assert res.status_code == 403
    assert "CSRF" in res.json()["detail"]
