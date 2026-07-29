# API一覧

全78エンドポイント。対話的な仕様は起動後に **http://localhost:8000/api/docs**（Swagger UI）で確認できます。

## 共通仕様

### 認証

ログイン成功時に2つの Cookie が発行されます。
トークンにはセッション版数（`sv`）とトークンID（`jti`）が含まれ、
ログアウトで `jti` が、パスワード変更・権限変更で `sv` が失効判定に使われます。

| Cookie | httpOnly | 用途 |
|---|:-:|---|
| `order_session` | ○ | JWT セッション（既定8時間） |
| `csrf_token` | × | CSRF ダブルサブミット用 |

**更新系リクエスト（POST / PUT / PATCH / DELETE）には `X-CSRF-Token` ヘッダが必須です。**
値は `csrf_token` Cookie と同じものを設定します。

外部システム連携など Cookie を使わない場合は `Authorization: Bearer <JWT>` も利用でき、
その場合 CSRF チェックは対象外です。

### 共通クエリパラメータ

多くの参照APIが以下を受け付けます。

| パラメータ | 型 | 説明 |
|---|---|---|
| `store_id` | int | 店舗で絞り込む。**管理者・本部のみ有効。**他ロールが自分以外を指定すると403 |
| `vendor_id` | int | ベンダーで絞り込む。**管理者・本部のみ有効。**同上 |
| `delivery_date` | date | 納品日（`YYYY-MM-DD`） |
| `date_from` / `date_to` | date | 納品日の範囲 |
| `limit` / `offset` | int | ページング |

### エラー応答

```json
{ "detail": "他ベンダーのデータにはアクセスできません" }
```

入力形式エラー（422）は具体的な項目名を返します。

```json
{ "detail": "入力内容を確認してください", "errors": ["items: 同じ商品が複数行に含まれています。..."] }
```

| コード | 意味 |
|---|---|
| 401 | 未認証・セッション期限切れ |
| 403 | 権限不足・CSRF不正・アカウント停止 |
| 404 | 対象が存在しない |
| 409 | 業務ルール上の競合（締め後変更、二重送信、version不一致、多重確定・多重承認など） |
| 422 | 入力形式エラー |
| 423 | ログイン失敗によるロック中 |

---

## 認証

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `POST` | `/api/auth/login` | ログイン。Cookie を発行 | 全員 |
| `POST` | `/api/auth/logout` | ログアウト。Cookie を削除 | 要ログイン |
| `GET` | `/api/auth/me` | ログイン中ユーザー情報（切替可否を含む） | 要ログイン |
| `POST` | `/api/auth/password` | 自分のパスワード変更 | 要ログイン |
| `POST` | `/api/auth/password-reset/request` | 再設定トークンの発行依頼 | 全員 |
| `POST` | `/api/auth/password-reset/confirm` | トークンでパスワード再設定 | 全員 |

**`POST /api/auth/login`**

```json
{ "email": "store1a@example.invalid", "password": "Password123!" }
```

```json
{
  "id": 4, "email": "store1a@example.invalid", "name": "みどり台店 担当A",
  "role_code": "STORE", "role_label": "店舗担当者",
  "store_id": 1, "store_name": "みどり台店",
  "vendor_id": null, "vendor_name": null,
  "can_switch_vendor": false, "can_switch_store": false,
  "last_login_at": "2026-07-29T01:23:45"
}
```

---

## 発注

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `GET` | `/api/orders` | 発注一覧（スコープ適用） | 全員 |
| `GET` | `/api/orders/{id}` | 発注明細 | 自分の範囲のみ |
| `GET` | `/api/orders/{id}/editable` | 締め状況と直接編集可否 | 自分の範囲のみ |
| `POST` | `/api/orders/validate` | 登録前の入力チェック | 管理者・本部・店舗 |
| `POST` | `/api/orders` | 発注登録（ベンダー別に自動分割） | 管理者・本部・店舗 |
| `PUT` | `/api/orders/{id}` | 締め前の数量修正（**`version` 必須**） | 管理者・本部・店舗 |
| `POST` | `/api/orders/{id}/confirm` | 発注確定 | 管理者・本部・店舗 |
| `POST` | `/api/orders/{id}/cancel` | 発注取消（理由必須） | 管理者・本部・店舗 |
| `GET` | `/api/orders/helpers/last-order` | 前回発注の内容（コピー入力用） | 管理者・本部・店舗 |
| `GET` | `/api/orders/helpers/recent-products` | 前回発注商品の一覧 | 管理者・本部・店舗 |

**`GET /api/orders`** の追加パラメータ: `status`（カンマ区切り）、`q`（発注番号の部分一致）、
`include_items`（明細を含めるか）

**`POST /api/orders`**

```json
{
  "store_id": 1,
  "delivery_date": "2026-08-05",
  "items": [
    { "product_id": 1, "qty_case": 2, "qty_loose": 3 },
    { "product_id": 11, "qty_case": 1, "qty_loose": 0 }
  ],
  "confirm": true,
  "client_token": "uuid-for-double-submit-prevention"
}
```

商品の担当ベンダーごとに発注が分割されるため、**戻り値は配列**です（201）。
`client_token` を同じ値で2回送ると 409（二重送信）になります。

**`PUT /api/orders/{id}`**

```json
{
  "version": 3,
  "items": [{ "id": 42, "product_id": 1, "qty_case": 5, "qty_loose": 0, "reason": "売上予測の変更" }]
}
```

`version` は必須で、発注を読み込んだ時点の値を送る。
他の担当者が先に更新していると **409** を返し、静かな上書きを防ぐ。
画面はこの 409 を確認ダイアログで表示し、最新内容の再読み込みを促す。

以下のステータスでは締め前でも **409** になる（ベンダー回答の前提が崩れるため）:
一部納品 / 欠品 / 代替提案 / 納品確定 / 変更申請中 / 変更承認済み / 変更却下 / 取消

**`POST /api/orders/validate`** の応答

```json
{
  "warnings": [
    { "code": "DUPLICATE_ORDER", "message": "架空牛乳 1000ml は同じ納品日に既に発注があります。...", "product_id": 1, "level": "WARN" }
  ],
  "blocking": false
}
```

| 警告コード | 内容 | レベル |
|---|---|---|
| `PAST_DELIVERY_DATE` | 納品日が過去日 | ERROR（登録不可） |
| `PRODUCT_NOT_FOUND` / `PRODUCT_INACTIVE` | 商品が存在しない・無効 | ERROR |
| `LOOSE_NOT_ALLOWED` | バラ発注不可の商品にバラ数を指定 | ERROR |
| `DUPLICATE_ORDER` | 同一店舗・同一商品・同一納品日の重複発注 | WARN |
| `ZERO_QUANTITY` | 数量が0 | WARN |
| `ABNORMAL_QUANTITY` | 異常数量（既定1000以上） | WARN |
| `COST_MISSING` | 原価未登録 | WARN |
| `CASE_QTY_MISMATCH` | バラ数がケース入数以上 | WARN |
| `ORDER_UNIT_MISMATCH` | 発注単位と入力の不整合 | WARN |
| `DEADLINE_PASSED` | 締め時間超過 | WARN |
| `DELIVERY_DATE_TOO_FAR` | 納品日が1年より先（年の打ち間違い） | ERROR |
| `PRODUCT_NOT_YET_VALID` / `PRODUCT_EXPIRED` | 適用期間外 | WARN |

---

## 締め後変更申請

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `GET` | `/api/change-requests` | 変更申請一覧 | 全員（スコープ適用） |
| `POST` | `/api/change-requests` | 変更申請の作成（**変更理由必須**） | 管理者・本部・店舗 |
| `POST` | `/api/change-requests/{id}/decision` | 承認・却下（却下は理由必須） | 管理者・本部 |
| `POST` | `/api/change-requests/{id}/vendor-confirm` | 変更内容のベンダー確認 | 該当ベンダー |

**`POST /api/change-requests`**

```json
{
  "order_item_id": 42,
  "requested_case": 4,
  "requested_loose": 0,
  "reason": "売上予測の変更",
  "client_token": "uuid"
}
```

- 締め **前** に呼ぶと 400（「発注画面から直接修正してください」）
- 申請しただけでは数量は変わらない。明細ステータスが `CHANGE_REQUESTED` になる
- 承認されて初めて `order_items` の数量が更新され、`order_histories` に
  `is_after_deadline=true` の履歴が記録される

---

## ベンダー回答

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `POST` | `/api/vendor/ack` | 受注確認 | 該当ベンダー |
| `POST` | `/api/vendor/responses` | 商品ごとの回答 | 該当ベンダー |
| `GET` | `/api/vendor/responses` | 回答履歴（`latest_only` で最新のみ） | 全員（スコープ適用） |
| `POST` | `/api/vendor/responses/{id}/substitute-decision` | 代替商品の承認・却下 | 管理者・本部 |
| `GET` | `/api/vendor/summary/by-product` | 商品別合計＋店舗別内訳 | 全員（スコープ適用） |
| `GET` | `/api/vendor/summary/by-delivery-date` | 納品日別集計 | 全員（スコープ適用） |
| `GET` | `/api/vendor/summary/by-store` | 店舗別数量 | 全員（スコープ適用） |

**`POST /api/vendor/responses`**

```json
{ "order_item_id": 42, "response_type": "PARTIAL", "deliverable_qty": 12, "reason": "生産遅延のため" }
```

| `response_type` | 必須項目 | 明細ステータス |
|---|---|---|
| `FULL` | — | `DELIVERED` |
| `PARTIAL` | `deliverable_qty`（発注数量未満かつ1以上）、`reason` | `PARTIAL` |
| `SHORTAGE` | `shortage_reason` | `SHORTAGE` |
| `SUBSTITUTE` | `sub_product_name`、`sub_deliverable_qty` | `SUBSTITUTE` |
| `CHECKING` / `CONSULT` | — | `VENDOR_ACK` |

数量・日付の制約（違反すると 400）:

- `deliverable_qty` / `sub_deliverable_qty` は発注数量を超えられない
- `next_available_date` / `sub_delivery_date` に過去日は指定できない
- `sub_cost` に負の値は指定できない（422）

回答を訂正しても過去の回答は残り、最新行のみ `is_latest=true` になります。
代替提案は本部が `substitute-decision` で承認するまで確定しません。

---

## マスタ

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `GET` | `/api/stores` | 店舗一覧 | 全員（店舗ユーザーは自店舗のみ） |
| `POST` / `PUT` / `DELETE` | `/api/stores[/{id}]` | 店舗の作成・更新・無効化 | 管理者 |
| `GET` | `/api/vendors` | ベンダー一覧 | 全員（ベンダーユーザーは自社のみ） |
| `POST` / `PUT` / `DELETE` | `/api/vendors[/{id}]` | ベンダーの作成・更新・無効化 | 管理者 |
| `GET` | `/api/products` | 商品検索（`q` / `category` / `vendor_id`） | 全員（ベンダーは自社商品のみ） |
| `GET` | `/api/products/categories` | 商品分類の一覧 | 全員 |
| `GET` | `/api/products/{id}` | 商品1件 | 全員（スコープ適用） |
| `POST` / `PUT` | `/api/products[/{id}]` | 商品の作成・更新 | 管理者・本部 |
| `DELETE` | `/api/products/{id}` | 商品の無効化 | 管理者 |
| `GET` | `/api/favorites` | お気に入り商品 | 管理者・本部・店舗 |
| `POST` / `DELETE` | `/api/favorites/{product_id}` | お気に入りの登録・解除 | 管理者・本部・店舗 |
| `GET` | `/api/users` | ユーザー一覧 | 管理者 |
| `POST` / `PUT` | `/api/users[/{id}]` | ユーザーの作成・更新 | 管理者 |
| `POST` | `/api/users/{id}/unlock` | ロック解除 | 管理者 |
| `DELETE` | `/api/users/{id}` | アカウント停止 | 管理者 |
| `GET` | `/api/roles` | 権限一覧 | 管理者 |
| `GET` | `/api/deadlines` | 締め時間設定 | 全員（スコープ適用） |
| `POST` / `PUT` / `DELETE` | `/api/deadlines[/{id}]` | 締め時間の作成・更新・削除 | 管理者・本部 |
| `GET` | `/api/reasons` | 理由マスタ（`kind=CHANGE` / `SHORTAGE`） | 全員 |
| `POST` / `DELETE` | `/api/reasons[/{id}]` | 理由の作成・削除 | 管理者・本部 |

---

## 履歴・通知

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `GET` | `/api/histories/quantity` | 数量変更履歴 | 全員（スコープ適用） |
| `GET` | `/api/histories/status` | ステータス変更履歴 | 全員（スコープ適用） |
| `GET` | `/api/histories/audit` | 操作ログ | 管理者・本部 |
| `GET` | `/api/histories/notification-logs` | 通知送信履歴 | 管理者・本部 |
| `GET` | `/api/histories/login` | ログイン履歴 | 管理者 |
| `GET` | `/api/notifications` | 自分あての通知 | 要ログイン |
| `GET` | `/api/notifications/unread-count` | 未読件数 | 要ログイン |
| `POST` | `/api/notifications/{id}/read` | 既読にする | 要ログイン |
| `POST` | `/api/notifications/read-all` | すべて既読にする | 要ログイン |

**履歴を削除するエンドポイントは存在しません。**

---

## ダッシュボード

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/api/dashboard` | 本日締め／未確定／ベンダー未確認／欠品／一部納品／代替提案／変更申請／回答期限超過の件数 |

---

## 出力

すべて `fmt` パラメータで形式を選べます（`xlsx` / `csv` / `pdf`）。
`pdf` は印刷用HTMLを返し、ブラウザの印刷ダイアログから PDF 保存します。

| メソッド | パス | 説明 | 権限 |
|---|---|---|---|
| `GET` | `/api/exports/orders` | 発注一覧（`group_by=vendor` / `store` / `none`） | 全員（スコープ適用） |
| `GET` | `/api/exports/product-summary` | 商品別集約 | 全員（スコープ適用） |
| `GET` | `/api/exports/delivery-date-summary` | 納品日別集約 | 全員（スコープ適用） |
| `GET` | `/api/exports/shortages` | 欠品一覧 | 全員（スコープ適用） |
| `GET` | `/api/exports/partials` | 一部納品一覧 | 全員（スコープ適用） |
| `GET` | `/api/exports/unanswered` | 未回答一覧 | 全員（スコープ適用） |
| `GET` | `/api/exports/change-requests` | 変更申請一覧 | 全員（スコープ適用） |
| `GET` | `/api/exports/order-histories` | 発注変更履歴 | 全員（スコープ適用） |
| `GET` | `/api/exports/audit-logs` | 操作ログ | 管理者・本部 |

`fmt=xlsx` かつ `group_by=vendor|store` の場合、ベンダー／店舗ごとにシートが分かれます。
CSV は Excel で文字化けしないよう BOM 付き UTF-8 で出力します。
すべての出力操作は `audit_logs` に記録されます。

---

## その他

| メソッド | パス | 説明 |
|---|---|---|
| `GET` | `/api/health` | ヘルスチェック |
| `GET` | `/api/meta` | 区分値の表示名一覧（ステータス・回答区分・権限など） |
| `GET` | `/api/docs` | Swagger UI |
| `GET` | `/api/openapi.json` | OpenAPI 定義 |
