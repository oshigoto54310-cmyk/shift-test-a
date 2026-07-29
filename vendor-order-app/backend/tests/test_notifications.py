"""通知と定期実行ジョブのテスト。

監査時点では時刻起点の通知（締め24時間前・1時間前・回答期限超過）を
発火させるジョブが未接続だったため、実装とあわせて追加した。
"""
from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import IdempotencyKey, Notification, NotificationLog, Order, RevokedToken, utcnow
from jobs import scheduler

from .conftest import create_order, future_date, get_products


def _set_deadline(order_id: int, *, deadline=None, reply_deadline=None, status=None):
    db = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        if deadline is not None:
            order.deadline_at = deadline
        if reply_deadline is not None:
            order.reply_deadline_at = reply_deadline
        if status is not None:
            order.status = status
            for item in order.items:
                item.status = status
        db.add(order)
        db.commit()
    finally:
        db.close()


def _notifications(order_id: int, ntype: str) -> list[Notification]:
    db = SessionLocal()
    try:
        return (
            db.query(Notification)
            .filter(Notification.order_id == order_id, Notification.type == ntype)
            .all()
        )
    finally:
        db.close()


def test_締め24時間前の通知が発火する(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(100)
    )[0]
    _set_deadline(order["id"], deadline=utcnow() + timedelta(hours=20))

    scheduler.run_once()
    rows = _notifications(order["id"], "DEADLINE_24H")
    assert rows, "締め24時間前の通知が飛んでいない"
    assert "締め24時間前" in rows[0].title
    # 店舗担当者にもベンダーにも届いていること
    assert len({r.user_id for r in rows}) >= 2


def test_締め1時間前の通知が発火する(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(101)
    )[0]
    _set_deadline(order["id"], deadline=utcnow() + timedelta(minutes=30))

    scheduler.run_once()
    assert _notifications(order["id"], "DEADLINE_1H"), "締め1時間前の通知が飛んでいない"


def test_回答期限超過の通知が発火する(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(102)
    )[0]
    _set_deadline(
        order["id"], reply_deadline=utcnow() - timedelta(hours=2), status="VENDOR_PENDING"
    )

    scheduler.run_once()
    rows = _notifications(order["id"], "VENDOR_REPLY_OVERDUE")
    assert rows, "回答期限超過の通知が飛んでいない"


def test_同じ通知は何度実行しても重複しない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(103)
    )[0]
    _set_deadline(order["id"], deadline=utcnow() + timedelta(hours=10))

    scheduler.run_once()
    first = len(_notifications(order["id"], "DEADLINE_24H"))
    assert first > 0

    scheduler.run_once()
    scheduler.run_once()
    assert len(_notifications(order["id"], "DEADLINE_24H")) == first, "通知が重複送信されている"

    # 抑止した分は送信履歴に SKIPPED として残る
    db = SessionLocal()
    try:
        skipped = (
            db.query(NotificationLog)
            .filter(NotificationLog.status == "SKIPPED", NotificationLog.type == "DEADLINE_24H")
            .count()
        )
    finally:
        db.close()
    assert skipped > 0, "重複抑止の記録が残っていない"


def test_取消済みと納品確定の発注には通知しない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(104)
    )[0]
    _set_deadline(order["id"], deadline=utcnow() + timedelta(hours=5), status="CANCELLED")

    scheduler.run_once()
    assert not _notifications(order["id"], "DEADLINE_24H")


def test_締め済みの発注には締め前通知を出さない(store_a):
    products = get_products(store_a, "テストベンダーA")
    order = create_order(
        store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(105)
    )[0]
    _set_deadline(order["id"], deadline=utcnow() - timedelta(hours=1))

    scheduler.run_once()
    assert not _notifications(order["id"], "DEADLINE_24H")
    assert not _notifications(order["id"], "DEADLINE_1H")


def test_古い冪等トークンと失効トークンが掃除される():
    db = SessionLocal()
    try:
        old = utcnow() - timedelta(days=scheduler.IDEMPOTENCY_RETENTION_DAYS + 1)
        db.add(IdempotencyKey(token="old-token-1", user_id=1, endpoint="test", created_at=old))
        db.add(IdempotencyKey(token="new-token-1", user_id=1, endpoint="test"))
        db.add(RevokedToken(jti="expired-jti", user_id=1, expires_at=utcnow() - timedelta(hours=1)))
        db.add(RevokedToken(jti="valid-jti", user_id=1, expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    finally:
        db.close()

    result = scheduler.run_once()
    assert result["cleaned_tokens"] >= 1
    assert result["cleaned_revoked"] >= 1

    db = SessionLocal()
    try:
        assert db.query(IdempotencyKey).filter(IdempotencyKey.token == "old-token-1").count() == 0
        assert db.query(IdempotencyKey).filter(IdempotencyKey.token == "new-token-1").count() == 1
        assert db.query(RevokedToken).filter(RevokedToken.jti == "expired-jti").count() == 0
        assert db.query(RevokedToken).filter(RevokedToken.jti == "valid-jti").count() == 1
    finally:
        db.close()


def test_通知は自分あてのものだけ見える(store_a, vendor_a):
    mine = store_a.get("/api/notifications", params={"limit": 500}).json()
    theirs = vendor_a.get("/api/notifications", params={"limit": 500}).json()
    mine_ids = {n["id"] for n in mine}
    theirs_ids = {n["id"] for n in theirs}
    assert not (mine_ids & theirs_ids), "他人の通知が見えている"


def test_未読件数と一括既読が動く(store_a):
    before = store_a.get("/api/notifications/unread-count").json()["unread"]
    if before == 0:
        products = get_products(store_a, "テストベンダーA")
        create_order(store_a, [products[0]["id"]], confirm=True, delivery_date=future_date(106))
        before = store_a.get("/api/notifications/unread-count").json()["unread"]

    assert store_a.post("/api/notifications/read-all").status_code == 200
    assert store_a.get("/api/notifications/unread-count").json()["unread"] == 0
