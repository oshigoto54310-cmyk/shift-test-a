# 今後の拡張候補

優先度順に記載します。「◎ 必須」は運用開始前に対応すべきものです。

---

## ◎ 1. 締め時間通知の定期実行（運用開始前に必要）

### 現状

通知の作成処理・重複防止・送信履歴は実装済みですが、
**時刻を起点とする通知（締め24時間前・1時間前、回答期限超過）を発火する
定期実行ジョブが未接続** です。現在は「発注登録」「確定」「回答」「変更申請」といった
**操作を起点とした通知のみ** が飛びます。

### 実装方法

`app/notify.py` の `notify_users()` をそのまま使えます。次のようなバッチを作成し、
15分間隔で実行してください。`dedup_key` により重複送信は自動的に防がれます。

```python
# backend/jobs/deadline_notifier.py
from datetime import timedelta
from app.database import SessionLocal
from app.constants import NotificationType, OrderStatus
from app.models import Order, utcnow
from app.notify import notify_users, order_stakeholders, vendor_users, hq_users

def run():
    db = SessionLocal()
    now = utcnow()
    try:
        for hours, ntype, label in [(24, NotificationType.DEADLINE_24H, "24時間"),
                                    (1, NotificationType.DEADLINE_1H, "1時間")]:
            target = now + timedelta(hours=hours)
            orders = db.query(Order).filter(
                Order.deleted_at.is_(None),
                Order.status.notin_([str(OrderStatus.CANCELLED)]),
                Order.deadline_at > now,
                Order.deadline_at <= target,
            ).all()
            for o in orders:
                notify_users(
                    db, order_stakeholders(db, o), notification_type=ntype,
                    title=f"締め{label}前 {o.order_no}",
                    body=f"納品日 {o.delivery_date:%Y/%m/%d} の締め時間が近づいています。",
                    dedup_key=f"deadline_{hours}h:{o.id}", order_id=o.id,
                )

        # 回答期限超過
        overdue = db.query(Order).filter(
            Order.deleted_at.is_(None),
            Order.status == str(OrderStatus.VENDOR_PENDING),
            Order.reply_deadline_at.isnot(None),
            Order.reply_deadline_at < now,
        ).all()
        for o in overdue:
            notify_users(
                db, vendor_users(db, o.vendor_id) + hq_users(db),
                notification_type=NotificationType.VENDOR_REPLY_OVERDUE,
                title=f"回答期限超過 {o.order_no}",
                body="ベンダー回答期限を過ぎています。至急ご確認ください。",
                dedup_key=f"reply_overdue:{o.id}", order_id=o.id,
            )
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    run()
```

**cron で実行する場合**

```cron
*/15 * * * * cd /app/backend && python -m jobs.deadline_notifier >> /var/log/notifier.log 2>&1
```

**docker compose にサービスを追加する場合**

```yaml
  notifier:
    build: { context: ., dockerfile: Dockerfile }
    depends_on: { db: { condition: service_healthy } }
    environment: *app_env
    command: sh -c "while true; do python -m jobs.deadline_notifier; sleep 900; done"
```

> 複数インスタンスで動かす場合は排他制御（DBの advisory lock 等）を入れてください。
> `dedup_key` があるため重複通知は防がれますが、無駄な処理は避けられます。

---

## ◎ 2. 冪等トークンの掃除

`idempotency_keys` は増え続けます。定期的に古い行を削除してください。

```sql
DELETE FROM idempotency_keys WHERE created_at < NOW() - INTERVAL '7 days';
```

上記の定期実行ジョブに含めるのが簡単です。

---

## 3. PWA プッシュ通知

通知基盤は拡張しやすい構造にしてあります。

- `notification_logs.channel` に `PUSH` を追加するだけでチャネルを増やせます
- `notify.py` の `_dispatch` 相当部分に Web Push の送信処理を追加します

必要な作業:

1. `manifest.json` と Service Worker の追加
2. VAPID 鍵の生成と `push_subscriptions` テーブルの追加
3. `pywebpush` などによる送信処理

---

## 4. 商品の複数ベンダー対応

`product_vendors` テーブルは作成済みで、主ベンダーが `is_primary=true` で1件入っています。

必要な作業:

1. 商品マスタ画面で副ベンダーを登録できるようにする
2. 発注入力時にベンダーを選択させる（未選択なら主ベンダー）
3. `create_order` の振り分けロジックを「選択されたベンダー」基準に変更

既存ロジックは主ベンダーで動くため、段階的に移行できます。

---

## 5. 納品実績の登録と検品

現在は「発注 → ベンダー回答」までで、実際に何が納品されたかは記録していません。

追加が必要なもの:

- `deliveries` / `delivery_items` テーブル
- 店舗側の検品画面（数量・欠品・破損の登録）
- 発注数量・回答数量・納品実績の3点比較

---

## 6. 発注テンプレート・定番発注

曜日ごとの定番発注をテンプレート化し、ワンタップで発注できるようにします。

- `order_templates` / `order_template_items` テーブル
- 「毎週月曜はこの内容」といった定期発注の自動生成

---

## 7. 発注実績の分析

- 商品別・店舗別・期間別の発注推移グラフ
- 欠品率・回答遅延率のベンダー評価
- 前年同週比

---

## 8. 締め時間の柔軟化

現在は「納品日の何日前・何時」という指定のみです。

- 曜日ごとの締め時間（土日祝の扱い）
- 祝日カレンダーの考慮
- リードタイムベースの指定

---

## 9. 操作性の改善

| 項目 | 内容 |
|---|---|
| バーコードスキャン | スマートフォンのカメラでJANコードを読み取り（`BarcodeDetector` API） |
| 一括入力の強化 | CSV貼り付けによる発注入力 |
| 音声入力 | 数量の音声入力 |
| オフライン一時保存 | IndexedDB による下書き保存（MVP対象外だが要望が多い想定） |

---

## 10. リアルタイム性の強化

現在は20秒間隔のポーリングです。同時利用者が増えた場合、
WebSocket または Server-Sent Events への移行を検討してください。

FastAPI は WebSocket に対応しているため、`/api/ws` を追加し、
発注更新時にイベントを配信する形にできます。

---

## 11. フロントエンドの Next.js 化

現在のフロントエンドはビルド不要の SPA です。
バックエンドは REST API のみを提供しているため、**API の変更なしに置き換えられます。**

移行時の作業:

1. Next.js プロジェクトを `frontend-next/` に作成
2. `Api` 相当のクライアントを実装（Cookie 認証と CSRF ヘッダの扱いは同じ）
3. `.env` に `CORS_ORIGINS=https://frontend.example.com` を設定
4. `main.py` の静的ファイル配信を無効化（または別ホストで配信）

---

## 12. 運用支援

| 項目 | 内容 |
|---|---|
| 監視 | Prometheus メトリクス、エラー通知（Sentry 等） |
| 構造化ログ | JSON ログ出力とログ集約基盤への転送 |
| 権限の細分化 | 「承認のみ可能」「参照のみ」といった役割の追加 |
| 多言語対応 | 外国人スタッフ向けの英語・ベトナム語表示 |

---

## 13. 流通BMS対応

[docs/bms.md](bms.md) を参照してください。
