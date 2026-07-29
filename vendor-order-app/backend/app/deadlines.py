"""締め時間の解決。

優先順位: 商品別 > ベンダー別 > システム標準
同一 scope 内では、納品日が明示された設定（スポット設定）を優先する。

締め時刻は日本時間で指定し、DBには UTC の naive datetime で保存する。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from .config import APP_TZ, settings
from .constants import DeadlineScope
from .models import Deadline, Product


def parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return time(12, 0)


def jst_to_utc(d: date, t: time) -> datetime:
    """日本時間の日付・時刻を UTC の naive datetime に変換する。"""
    local = datetime.combine(d, t, tzinfo=APP_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def utc_to_jst(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(APP_TZ)


@dataclass
class DeadlineSet:
    rough_deadline_at: datetime   # 概算締め（UTC naive）
    final_deadline_at: datetime   # 最終締め（UTC naive）
    reply_deadline_at: datetime   # ベンダー回答期限（UTC naive）
    source: str                   # PRODUCT / VENDOR / SYSTEM
    source_id: int | None


def _system_default() -> Deadline:
    """DBにシステム標準行が無い場合に使う既定値。"""
    return Deadline(
        scope=str(DeadlineScope.SYSTEM),
        rough_days_before=settings.default_rough_days_before,
        rough_time="12:00",
        final_days_before=settings.default_final_days_before,
        final_time=settings.default_final_time,
        reply_days_before=settings.default_reply_days_before,
        reply_time=settings.default_reply_time,
        is_active=True,
    )


def _pick(rows: list[Deadline], delivery_date: date) -> Deadline | None:
    """納品日指定あり（スポット）を優先し、無ければ恒常設定を返す。"""
    spot = [r for r in rows if r.delivery_date == delivery_date]
    if spot:
        return spot[0]
    general = [r for r in rows if r.delivery_date is None]
    return general[0] if general else None


def resolve_deadline(
    db: Session,
    *,
    delivery_date: date,
    vendor_id: int,
    product_id: int | None = None,
) -> DeadlineSet:
    """納品日・ベンダー・商品から適用される締め時間を決定する。"""
    base_q = db.query(Deadline).filter(
        Deadline.is_active.is_(True), Deadline.deleted_at.is_(None)
    )

    chosen: Deadline | None = None
    source = str(DeadlineScope.SYSTEM)
    source_id: int | None = None

    if product_id is not None:
        rows = base_q.filter(
            Deadline.scope == str(DeadlineScope.PRODUCT), Deadline.product_id == product_id
        ).all()
        chosen = _pick(rows, delivery_date)
        if chosen:
            source, source_id = str(DeadlineScope.PRODUCT), chosen.id

    if chosen is None:
        rows = base_q.filter(
            Deadline.scope == str(DeadlineScope.VENDOR), Deadline.vendor_id == vendor_id
        ).all()
        chosen = _pick(rows, delivery_date)
        if chosen:
            source, source_id = str(DeadlineScope.VENDOR), chosen.id

    if chosen is None:
        rows = base_q.filter(Deadline.scope == str(DeadlineScope.SYSTEM)).all()
        chosen = _pick(rows, delivery_date)
        if chosen:
            source, source_id = str(DeadlineScope.SYSTEM), chosen.id

    if chosen is None:
        chosen = _system_default()
        source, source_id = str(DeadlineScope.SYSTEM), None

    rough = jst_to_utc(
        delivery_date - timedelta(days=chosen.rough_days_before), parse_hhmm(chosen.rough_time)
    )
    final = jst_to_utc(
        delivery_date - timedelta(days=chosen.final_days_before), parse_hhmm(chosen.final_time)
    )
    reply = jst_to_utc(
        delivery_date - timedelta(days=chosen.reply_days_before), parse_hhmm(chosen.reply_time)
    )
    return DeadlineSet(
        rough_deadline_at=rough,
        final_deadline_at=final,
        reply_deadline_at=reply,
        source=source,
        source_id=source_id,
    )


def resolve_order_deadline(
    db: Session, *, delivery_date: date, vendor_id: int, product_ids: list[int] | None = None
) -> DeadlineSet:
    """発注（複数明細）に対する締め時間。

    明細ごとに商品別締めが異なりうるため、発注ヘッダには **最も早い最終締め** を採用する。
    こうすると「一部の商品はもう締まっているのにヘッダ上は締め前」という状態を避けられる。
    """
    if not product_ids:
        return resolve_deadline(db, delivery_date=delivery_date, vendor_id=vendor_id)

    sets = [
        resolve_deadline(db, delivery_date=delivery_date, vendor_id=vendor_id, product_id=pid)
        for pid in product_ids
    ]
    earliest = min(sets, key=lambda s: s.final_deadline_at)
    return DeadlineSet(
        rough_deadline_at=min(s.rough_deadline_at for s in sets),
        final_deadline_at=earliest.final_deadline_at,
        reply_deadline_at=min(s.reply_deadline_at for s in sets),
        source=earliest.source,
        source_id=earliest.source_id,
    )


def item_deadline(db: Session, *, delivery_date: date, vendor_id: int, product: Product) -> DeadlineSet:
    return resolve_deadline(
        db, delivery_date=delivery_date, vendor_id=vendor_id, product_id=product.id
    )
