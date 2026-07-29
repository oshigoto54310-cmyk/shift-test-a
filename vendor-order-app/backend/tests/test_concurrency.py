"""同時更新・競合の回帰テスト。

第三者監査で以下が実際に再現したため、その再発防止として追加した。
- 3並列の発注確定がすべて成功していた
- 3並列の変更申請承認がすべて成功し、承認履歴が3件記録されていた
- 2人が同じ発注を編集すると後勝ちで静かに上書きされていた
- 10並列の発注登録で発注番号が衝突し 9件が 500 になっていた
"""
from __future__ import annotations

import threading

from app.database import SessionLocal
from app.models import ChangeRequest, Order, OrderHistory, OrderStatusHistory

from .conftest import (
    create_order,
    force_deadline_passed,
    future_date,
    get_products,
    make_client,
)


def _run_parallel(fn, args_list):
    """同じ操作を並列に実行して、結果を集める。"""
    results: list = []
    lock = threading.Lock()

    def worker(arg):
        result = fn(arg)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(a,)) for a in args_list]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# --------------------------------------------------------------------------
# 楽観ロック
# --------------------------------------------------------------------------
def test_同じ発注を2人が編集すると後発は拒否される(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], qty_case=2, delivery_date=future_date(50))[0]
    other = make_client("storea2@test.invalid")

    # 2人が同じ時点の画面を開く
    view_a = store_a.get(f"/api/orders/{order['id']}").json()
    view_b = other.get(f"/api/orders/{order['id']}").json()
    assert view_a["version"] == view_b["version"]
    item = view_a["items"][0]

    body = lambda version, qty: {  # noqa: E731
        "version": version,
        "items": [{"id": item["id"], "product_id": item["product_id"],
                   "qty_case": qty, "qty_loose": 0, "reason": "監査"}],
    }

    first = store_a.put(f"/api/orders/{order['id']}", json=body(view_a["version"], 10))
    second = other.put(f"/api/orders/{order['id']}", json=body(view_b["version"], 20))

    assert first.status_code == 200
    assert second.status_code == 409, "古い version での上書きが通ってしまっている"
    assert "他の担当者" in second.json()["detail"]

    # 先に保存した内容が残っていること（静かに上書きされていない）
    final = store_a.get(f"/api/orders/{order['id']}").json()
    assert final["items"][0]["qty_case"] == 10
    assert final["version"] == view_a["version"] + 1


def test_最新versionを読み直せば保存できる(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(51))[0]
    other = make_client("storea2@test.invalid")
    view = store_a.get(f"/api/orders/{order['id']}").json()
    item = view["items"][0]

    store_a.put(f"/api/orders/{order['id']}", json={
        "version": view["version"],
        "items": [{"id": item["id"], "product_id": item["product_id"], "qty_case": 5, "qty_loose": 0}],
    })
    fresh = other.get(f"/api/orders/{order['id']}").json()
    res = other.put(f"/api/orders/{order['id']}", json={
        "version": fresh["version"],
        "items": [{"id": item["id"], "product_id": item["product_id"], "qty_case": 8, "qty_loose": 0}],
    })
    assert res.status_code == 200
    assert store_a.get(f"/api/orders/{order['id']}").json()["items"][0]["qty_case"] == 8


def test_versionを送らない更新は拒否される(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(52))[0]
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    res = store_a.put(f"/api/orders/{order['id']}", json={
        "items": [{"id": item["id"], "product_id": item["product_id"], "qty_case": 3, "qty_loose": 0}],
    })
    assert res.status_code == 422, "version 未指定を許すと静かな上書きが起きる"


def test_同一versionでの並列更新は1件しか成功しない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(53))[0]
    view = store_a.get(f"/api/orders/{order['id']}").json()
    item = view["items"][0]

    clients = [make_client("storea@test.invalid") for _ in range(6)]

    def put(idx):
        return clients[idx].put(f"/api/orders/{order['id']}", json={
            "version": view["version"],
            "items": [{"id": item["id"], "product_id": item["product_id"],
                       "qty_case": idx + 1, "qty_loose": 0}],
        }).status_code

    codes = _run_parallel(put, range(len(clients)))
    assert codes.count(200) == 1, f"並列更新が複数成功している: {codes}"
    assert all(c in (200, 409) for c in codes), f"想定外の応答: {codes}"


# --------------------------------------------------------------------------
# 状態遷移の排他
# --------------------------------------------------------------------------
def test_並列の発注確定は1件しか成功しない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(54))[0]
    clients = [make_client("storea@test.invalid") for _ in range(5)]

    codes = _run_parallel(
        lambda c: c.post(f"/api/orders/{order['id']}/confirm", json={}).status_code, clients
    )
    assert codes.count(200) == 1, f"多重確定が発生している: {codes}"

    db = SessionLocal()
    try:
        confirmed = (
            db.query(OrderStatusHistory)
            .filter(
                OrderStatusHistory.order_id == order["id"],
                OrderStatusHistory.order_item_id.is_(None),
                OrderStatusHistory.status_after == "CONFIRMED",
            )
            .count()
        )
    finally:
        db.close()
    assert confirmed == 1, f"確定履歴が {confirmed} 件記録されている"


def test_並列の変更申請承認は1件しか成功しない(store_a, hq):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, qty_case=2, delivery_date=future_date(55)
    )[0]
    force_deadline_passed(order["id"])
    item = store_a.get(f"/api/orders/{order['id']}").json()["items"][0]
    cr = store_a.post("/api/change-requests", json={
        "order_item_id": item["id"], "requested_case": 7, "requested_loose": 0, "reason": "監査",
    }).json()

    approvers = [make_client("hq@test.invalid") for _ in range(4)]
    codes = _run_parallel(
        lambda c: c.post(
            f"/api/change-requests/{cr['id']}/decision", json={"approve": True}
        ).status_code,
        approvers,
    )
    assert codes.count(200) == 1, f"多重承認が発生している: {codes}"

    db = SessionLocal()
    try:
        histories = (
            db.query(OrderHistory).filter(OrderHistory.change_request_id == cr["id"]).count()
        )
        record = db.query(ChangeRequest).filter(ChangeRequest.id == cr["id"]).first()
    finally:
        db.close()
    assert histories == 1, f"承認履歴が {histories} 件記録されている"
    assert record.status == "APPROVED"

    # 数量は1回だけ反映される
    assert store_a.get(f"/api/orders/{order['id']}").json()["items"][0]["qty_case"] == 7


def test_並列の発注取消は1件しか成功しない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(store_a, [products[0]["id"]], delivery_date=future_date(56))[0]
    clients = [make_client("storea@test.invalid") for _ in range(4)]
    codes = _run_parallel(
        lambda c: c.post(
            f"/api/orders/{order['id']}/cancel", json={"reason": "監査"}
        ).status_code,
        clients,
    )
    assert codes.count(200) == 1, f"多重取消が発生している: {codes}"


# --------------------------------------------------------------------------
# 採番の競合
# --------------------------------------------------------------------------
def test_並列の発注登録でも発注番号が衝突しない(store_b):
    products = get_products(store_b, "テストベンダーA")
    delivery = future_date(57)
    clients = [make_client("storeb@test.invalid") for _ in range(8)]

    def create(c):
        res = c.post("/api/orders", json={
            "delivery_date": delivery,
            "items": [{"product_id": products[0]["id"], "qty_case": 1, "qty_loose": 0}],
        })
        return (res.status_code, res.json()[0]["order_no"] if res.status_code == 201 else None)

    results = _run_parallel(create, clients)
    codes = [r[0] for r in results]
    numbers = [r[1] for r in results if r[1]]

    assert all(c < 500 for c in codes), f"サーバーエラーが発生している: {codes}"
    assert codes.count(201) == len(clients), f"登録に失敗したリクエストがある: {codes}"
    assert len(set(numbers)) == len(numbers), f"発注番号が重複している: {numbers}"

    db = SessionLocal()
    try:
        stored = db.query(Order).filter(Order.order_no.in_(numbers)).count()
    finally:
        db.close()
    assert stored == len(numbers)
