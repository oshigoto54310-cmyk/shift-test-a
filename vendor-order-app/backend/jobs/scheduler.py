"""時刻を起点とする通知の定期実行ジョブ。

操作起点の通知（発注登録・確定・回答・変更申請）はAPI側で送っているが、
「締め24時間前」「締め1時間前」「回答期限超過」は誰の操作でもないため、
このジョブが定期的に発火させる。

重複送信は notifications の (user_id, dedup_key) UNIQUE 制約で防いでいるため、
実行間隔が短くても同じ通知が二重に飛ぶことはない。

使い方:
    python -m jobs.scheduler once     # 1回だけ実行（cron 向け）
    python -m jobs.scheduler loop     # 常駐して定期実行（docker compose 向け）
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.constants import NotificationType, OrderStatus  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.deadlines import utc_to_jst  # noqa: E402
from app.models import IdempotencyKey, Order, OrderItem, RevokedToken, utcnow  # noqa: E402
from app.notify import (  # noqa: E402
    hq_users,
    notify_users,
    order_stakeholders,
    vendor_users,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s [notifier] %(message)s"
)
logger = logging.getLogger(__name__)

# 実行間隔（秒）。締め1時間前通知を取りこぼさないよう、1時間より十分短くする。
INTERVAL_SECONDS = 900

# 冪等トークンの保持期間（日）。これより古い行は掃除する。
IDEMPOTENCY_RETENTION_DAYS = 7

# 通知対象外のステータス
INACTIVE_STATUSES = [str(OrderStatus.CANCELLED), str(OrderStatus.DELIVERED)]


def _active_orders(db, *, statuses: list[str] | None = None):
    q = db.query(Order).filter(
        Order.deleted_at.is_(None), Order.status.notin_(INACTIVE_STATUSES)
    )
    if statuses:
        q = q.filter(Order.status.in_(statuses))
    return q


def notify_deadline_approaching(db) -> int:
    """締め24時間前・1時間前の通知。

    「now から hours 以内に締めを迎える」発注が対象。
    dedup_key に発注IDと種別を含めるため、何度実行しても1回しか飛ばない。
    """
    now = utcnow()
    sent = 0
    for hours, ntype, label in (
        (24, NotificationType.DEADLINE_24H, "24時間"),
        (1, NotificationType.DEADLINE_1H, "1時間"),
    ):
        limit = now + timedelta(hours=hours)
        orders = (
            _active_orders(db)
            .filter(Order.deadline_at.isnot(None))
            .filter(Order.deadline_at > now, Order.deadline_at <= limit)
            .all()
        )
        for order in orders:
            deadline_jst = utc_to_jst(order.deadline_at)
            created = notify_users(
                db,
                order_stakeholders(db, order),
                notification_type=ntype,
                title=f"締め{label}前 {order.order_no}",
                body=(
                    f"納品日 {order.delivery_date:%Y/%m/%d} の発注は "
                    f"{deadline_jst:%m/%d %H:%M} に締め切られます。"
                    "修正がある場合は締め切り前にお願いします。"
                ),
                dedup_key=f"deadline_{hours}h:{order.id}",
                order_id=order.id,
            )
            sent += len(created)
    return sent


def notify_vendor_unconfirmed(db) -> int:
    """ベンダーが未確認のまま回答期限が迫っている発注をベンダーに知らせる。"""
    now = utcnow()
    soon = now + timedelta(hours=6)
    orders = (
        _active_orders(db, statuses=[str(OrderStatus.CONFIRMED), str(OrderStatus.VENDOR_PENDING)])
        .filter(Order.reply_deadline_at.isnot(None))
        .filter(Order.reply_deadline_at > now, Order.reply_deadline_at <= soon)
        .all()
    )
    sent = 0
    for order in orders:
        reply_jst = utc_to_jst(order.reply_deadline_at)
        created = notify_users(
            db,
            vendor_users(db, order.vendor_id),
            notification_type=NotificationType.VENDOR_UNCONFIRMED,
            title=f"回答期限が近づいています {order.order_no}",
            body=f"回答期限は {reply_jst:%m/%d %H:%M} です。受注確認と回答をお願いします。",
            dedup_key=f"vendor_unconfirmed:{order.id}",
            order_id=order.id,
        )
        sent += len(created)
    return sent


def notify_reply_overdue(db) -> int:
    """回答期限を過ぎても未回答の明細を、ベンダーと本部に知らせる。"""
    now = utcnow()
    rows = (
        db.query(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            Order.deleted_at.is_(None),
            OrderItem.deleted_at.is_(None),
            OrderItem.status == str(OrderStatus.VENDOR_PENDING),
            Order.reply_deadline_at.isnot(None),
            Order.reply_deadline_at < now,
        )
        .distinct()
        .all()
    )
    sent = 0
    for order in rows:
        reply_jst = utc_to_jst(order.reply_deadline_at)
        created = notify_users(
            db,
            vendor_users(db, order.vendor_id) + hq_users(db),
            notification_type=NotificationType.VENDOR_REPLY_OVERDUE,
            title=f"回答期限超過 {order.order_no}",
            body=(
                f"回答期限（{reply_jst:%m/%d %H:%M}）を過ぎても未回答の明細があります。"
                "至急ご確認ください。"
            ),
            dedup_key=f"reply_overdue:{order.id}",
            order_id=order.id,
        )
        sent += len(created)
    return sent


def cleanup_idempotency_keys(db) -> int:
    """古い二重送信防止トークンを削除する（放置すると増え続けるため）。"""
    threshold = utcnow() - timedelta(days=IDEMPOTENCY_RETENTION_DAYS)
    deleted = (
        db.query(IdempotencyKey).filter(IdempotencyKey.created_at < threshold).delete()
    )
    return deleted


def cleanup_revoked_tokens(db) -> int:
    """有効期限が切れた失効トークンを削除する。

    期限切れのトークンは失効リストに無くても JWT 検証で弾かれるため、
    残しておく意味がない。
    """
    return db.query(RevokedToken).filter(RevokedToken.expires_at < utcnow()).delete()


def run_once() -> dict[str, int]:
    """1巡分の処理。cron からはこれを呼ぶ。"""
    db = SessionLocal()
    try:
        result = {
            "deadline": notify_deadline_approaching(db),
            "vendor_unconfirmed": notify_vendor_unconfirmed(db),
            "reply_overdue": notify_reply_overdue(db),
            "cleaned_tokens": cleanup_idempotency_keys(db),
            "cleaned_revoked": cleanup_revoked_tokens(db),
        }
        db.commit()
        logger.info(
            "締め通知=%d 未確認通知=%d 期限超過通知=%d 冪等トークン削除=%d 失効トークン削除=%d",
            result["deadline"], result["vendor_unconfirmed"], result["reply_overdue"],
            result["cleaned_tokens"], result["cleaned_revoked"],
        )
        return result
    except Exception:
        db.rollback()
        logger.exception("通知ジョブでエラーが発生しました")
        raise
    finally:
        db.close()


def run_loop(interval: int = INTERVAL_SECONDS) -> None:
    """常駐実行。1回の失敗で止めず、次の周期で再試行する。"""
    logger.info("通知ジョブを開始します（%d秒間隔）", interval)
    while True:
        try:
            run_once()
        except Exception:  # pragma: no cover - 常駐時の保険
            logger.warning("この周期はスキップし、次回に再試行します")
        time.sleep(interval)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    if mode == "loop":
        run_loop()
    else:
        run_once()
