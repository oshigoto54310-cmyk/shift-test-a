# ベンダー別・発注管理Webアプリ

スーパー本部・店舗・ベンダー間の発注業務を、電話・LINE・FAXに頼らず一元管理する
**ログイン機能付きの業務用Webアプリ**です。一般公開用のホームページではありません。

発注内容・数量変更・ベンダー回答・欠品・減数・代替提案・締め時間・承認履歴をすべて
サーバー側に保存し、「言った・言わない」を防止します。

---

## 目次

- [できること](#できること)
- [技術構成](#技術構成)
- [セットアップ手順](#セットアップ手順)
- [起動手順](#起動手順)
- [動作確認用アカウント](#動作確認用アカウント)
- [自動テスト](#自動テスト)
- [本番運用（PostgreSQL / Docker / HTTPS）](#本番運用postgresql--docker--https)
- [ドキュメント一覧](#ドキュメント一覧)
- [MVP完成条件の達成状況](#mvp完成条件の達成状況)
- [セキュリティ上の注意点](#セキュリティ上の注意点)
- [今後の拡張候補](#今後の拡張候補)

---

## できること

### 権限ごとの役割

| 権限 | 主な操作 |
|---|---|
| 管理者 | 全店舗・全ベンダー閲覧、ベンダー／店舗切替、ユーザー管理、各種マスタ管理、全履歴閲覧、アカウント停止、データ出力 |
| 本部担当者 | 全店舗・全ベンダー閲覧、ベンダー／店舗切替、発注登録・修正・確定、ベンダー回答確認、締め後変更承認、欠品・減数確認、Excel/CSV/PDF出力 |
| 店舗担当者 | **自店舗のみ** 発注登録・締め前修正・確定・履歴閲覧、ベンダー回答確認、締め後変更申請 |
| ベンダー担当者 | **自ベンダーのみ** 受注確認、全数納品／一部納品／欠品／代替提案の回答、店舗別・商品別数量の閲覧、回答履歴 |

### データ分離（この仕組みが本アプリの中核です）

- 店舗ユーザー・ベンダーユーザーの絞り込みは **サーバー側で強制** します。
- URL や API パラメータ（`?vendor_id=2` など）を書き換えても、権限外のデータには到達できず **403** を返します。
- ベンダーユーザーには他ベンダーが一覧にも出ないため、そもそも切替UIを構成できません。
- 出力（Excel / CSV / PDF）にも同じスコープが適用されます。

これらは推測ではなく [自動テスト](backend/tests/test_permissions.py) で検証されています。

### 締め時間

適用の優先順位は **商品別 → ベンダー別 → システム標準** です。

| 種別 | 標準設定 |
|---|---|
| 概算締め | 納品日の3日前 |
| 最終締め | 納品日前日の12:00 |
| ベンダー回答期限 | 納品日前日の15:00 |

- **締め前**: 数量を直接修正でき、修正のたびに履歴が残ります。
- **締め後**: 直接の上書きは **409 で拒否** されます。変更理由を必須とした「変更申請」を作成し、
  本部または管理者の承認を経て初めて数量が更新されます。変更前数量は保持され、履歴は削除できません。

---

## 技術構成

```
vendor-order-app/
├── backend/                 FastAPI（REST API）
│   ├── app/
│   │   ├── main.py          アプリ本体・セキュリティヘッダ
│   │   ├── config.py        設定（すべて環境変数から）
│   │   ├── database.py      DB接続（SQLite / PostgreSQL 両対応）
│   │   ├── models.py        SQLAlchemy モデル
│   │   ├── schemas.py       API入出力スキーマ
│   │   ├── security.py      bcrypt / JWT / CSRF
│   │   ├── deps.py          ★ 認証・権限・スコープ強制
│   │   ├── services.py      発注共通ロジック・履歴保存
│   │   ├── deadlines.py     締め時間の解決
│   │   ├── notify.py        アプリ内通知・メール通知
│   │   ├── audit.py         操作ログ
│   │   └── routers/         auth / masters / orders / vendor /
│   │                        change_requests / histories / dashboard / exports
│   ├── alembic/             マイグレーション
│   ├── jobs/scheduler.py    締め通知・期限超過通知の定期実行ジョブ
│   ├── tests/               自動テスト（141件）
│   └── seed.py              初期テストデータ（架空データ）
├── frontend/                スマートフォン対応SPA
│   ├── index.html
│   └── static/  api.js / ui.js / app.js / styles.css
├── docs/                    設計書・監査報告・マニュアル
├── scripts/                 backup.sh / restore.sh
├── Dockerfile
├── docker-compose.yml
├── nginx.conf               HTTPS終端の設定例
└── .env.example
```

| 項目 | 採用技術 |
|---|---|
| バックエンド | FastAPI (Python 3.11) |
| ORM | SQLAlchemy 2.0 |
| マイグレーション | Alembic |
| データベース | 開発 SQLite / 本番 PostgreSQL（`DATABASE_URL` の差し替えのみで移行可） |
| 認証 | JWT（httpOnly Cookie）＋ CSRF ダブルサブミット |
| パスワード | bcrypt（コスト12） |
| フロントエンド | 依存パッケージ不要の SPA（HTML + CSS + Vanilla JS） |
| 出力 | openpyxl（Excel）、CSV（BOM付きUTF-8）、印刷用HTML（ブラウザからPDF保存） |
| コンテナ | Docker / docker compose |

### フロントエンドについて（構成上の判断）

仕様書では Next.js が推奨されていましたが、本実装では **ビルド不要の SPA** を採用しました。
理由は次のとおりです。

- 現場のスマートフォンから即座に開ける（ビルド成果物やNode実行環境が不要）
- 導入・保守の手間が小さい（`docker compose up` だけで動く）

**フロントエンドとバックエンドの責務は分離されています。** 画面は `/api/*` の
REST API のみを通じてデータを取得し、業務ロジックと権限判定はすべてサーバー側にあります。
そのため、将来 Next.js / React に置き換える場合も **APIをそのまま利用でき、
バックエンドの変更は不要** です（別ホストで動かす場合は `CORS_ORIGINS` の設定のみ追加）。

---

## セットアップ手順

### 前提

- Python 3.11 以上
- （本番）Docker / Docker Compose

### 1. 依存パッケージのインストール

```bash
cd vendor-order-app/backend
python3 -m venv .venv
source .venv/bin/activate        # Windows は .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 環境変数の設定

```bash
cd ..                            # vendor-order-app/
cp .env.example .env
```

`.env` を開き、最低限 `SECRET_KEY` を変更してください。

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> `.env` は `.gitignore` 済みです。**秘密鍵やパスワードをコミットしないでください。**

### 3. データベースの作成と初期データ投入

```bash
cd backend
python seed.py --reset
```

`--reset` は既存データをすべて削除して作り直します。初回は `--reset` なしでも構いません。

---

## 起動手順

```bash
cd vendor-order-app/backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

| URL | 内容 |
|---|---|
| http://localhost:8000/ | アプリ画面（ログイン） |
| http://localhost:8000/api/docs | API仕様（Swagger UI） |
| http://localhost:8000/api/health | ヘルスチェック |

### スマートフォンからの実機確認

1. PC とスマートフォンを同じ Wi-Fi に接続する
2. PC の IP アドレスを確認する（`ipconfig` / `ip addr`）
3. `--host 0.0.0.0` で起動する（上記コマンドのとおり）
4. スマートフォンのブラウザで `http://<PCのIPアドレス>:8000/` を開く

---

## 動作確認用アカウント

`seed.py` が投入する **架空データ** です。実在する企業・店舗・担当者・メールアドレス・JANコードは
一切使用していません（`.invalid` は RFC 2606 で予約されたテスト用ドメインです）。

| 権限 | メールアドレス | パスワード |
|---|---|---|
| 管理者 | `admin@example.invalid` | `Password123!` |
| 本部担当者 | `hq1@example.invalid` / `hq2@example.invalid` | `Password123!` |
| 店舗担当者 | `store1a@example.invalid` 〜 `store3b@example.invalid` | `Password123!` |
| ベンダー担当者 | `vendor1a@example.invalid` 〜 `vendor2b@example.invalid` | `Password123!` |

投入されるデータ: 本部2名 / 店舗3店舗・各2名 / ベンダー2社・各2名 / 商品20件 /
発注30件 / 欠品3件 / 一部納品3件 / 締め後変更申請3件。

> **本番では必ず全アカウントのパスワードを変更してください。**

---

## 自動テスト

```bash
cd vendor-order-app/backend
python -m pytest
```

```
141 passed
```

テストは一時ファイルの SQLite を使うため、開発用DBを壊しません。
カバレッジは 84%（`python -m pytest --cov=app --cov=jobs`）。

| ファイル | 件数 | 内容 |
|---|--:|---|
| `tests/test_permissions.py` | 15 | ベンダー間・店舗間のデータ分離、切替可否、管理画面アクセス、ログインロック、CSRF |
| `tests/test_idor.py` | 16 | 全リソースについて、連番IDの直接指定で他社・他店舗に到達できないこと |
| `tests/test_orders.py` | 17 | 締め前修正、締め後の直接変更拒否、変更申請と承認、数量変更履歴、二重発注警告、二重送信防止、締め時間の優先順位、ベンダー自動振り分け、操作ログ |
| `tests/test_concurrency.py` | 8 | 楽観ロック、並列確定・並列承認・並列取消の排他、発注番号の同時採番 |
| `tests/test_transitions.py` | 7 | ベンダー回答後の直接編集・取消の禁止、取消済み・確定済みの再操作禁止 |
| `tests/test_validation.py` | 17 | 数量・日付・原価の境界値、締め時刻の日付境界（年末・月末・うるう日）、タイムゾーン整合 |
| `tests/test_auth_session.py` | 11 | ログアウト・パスワード変更・権限変更でのセッション失効、トークン改ざん、平文保存されていないこと |
| `tests/test_vendor_responses.py` | 10 | 自社発注のみ回答可、一部納品の数量・理由必須、欠品理由必須、代替提案の本部承認、回答履歴の保持 |
| `tests/test_dashboard.py` | 11 | 集計値の正しさ、スコープ適用、日本時間での当日判定 |
| `tests/test_notifications.py` | 9 | 締め24時間前・1時間前・回答期限超過の発火、重複抑止、トークン掃除 |
| `tests/test_exports.py` | 9 | ベンダー／店舗／本部それぞれの出力スコープ、Excelシート分割、出力形式、出力の操作ログ記録 |

---

## 本番運用（PostgreSQL / Docker / HTTPS）

### 1. 環境変数

```bash
cp .env.example .env
```

本番では以下を必ず設定してください。

```dotenv
ENVIRONMENT=production
SECRET_KEY=<推測不可能な値>
COOKIE_SECURE=true                # HTTPS 必須
POSTGRES_PASSWORD=<強固なパスワード>
DATABASE_URL=postgresql+psycopg://order_user:<パスワード>@db:5432/order_app
```

### 2. 起動

```bash
docker compose up -d --build
```

`app` コンテナは起動時に `alembic upgrade head` を実行してからサーバーを立ち上げます。
`ENVIRONMENT=production` の場合、起動時の自動テーブル作成は行わず、マイグレーションのみで
スキーマを管理します。

### 3. 初期データ

本番で管理者アカウントだけ作る場合は、コンテナ内で Python から作成してください
（`seed.py` は架空の取引データも投入するため、本番には使わないでください）。

```bash
docker compose exec app python -c "
from app.database import SessionLocal
from app.models import Role, User
from app.security import hash_password
db = SessionLocal()
role = db.query(Role).filter(Role.code=='ADMIN').first()
if role is None:
    for code, name in [('ADMIN','管理者'),('HQ','本部担当者'),('STORE','店舗担当者'),('VENDOR','ベンダー担当者')]:
        db.add(Role(code=code, name=name))
    db.commit()
    role = db.query(Role).filter(Role.code=='ADMIN').first()
db.add(User(email='admin@your-domain.example', name='管理者',
            password_hash=hash_password('ここに初期パスワード'),
            role_id=role.id, is_active=True))
db.commit(); print('管理者を作成しました')
"
```

作成後すぐにログインし、パスワードを変更してください。

### 4. HTTPS

`certs/server.crt` と `certs/server.key` を配置し、`nginx.conf` の `server_name` を
実際のドメインに書き換えたうえで起動します。

```bash
docker compose --profile https up -d
```

### 5. 定期バックアップ

`./backups` が `db` コンテナにマウントされています。cron から次を実行してください。

```bash
docker compose exec -T db pg_dump -U order_user order_app \
  | gzip > ./backups/order_app_$(date +%Y%m%d_%H%M).sql.gz

# 世代管理（30日より古いものを削除）
find ./backups -name '*.sql.gz' -mtime +30 -delete
```

リストア:

```bash
gunzip -c ./backups/order_app_YYYYMMDD_HHMM.sql.gz \
  | docker compose exec -T db psql -U order_user -d order_app
```

---

## ドキュメント一覧

| ファイル | 内容 |
|---|---|
| [docs/database.md](docs/database.md) | データベース設計書（全テーブル・カラム定義） |
| [docs/screens.md](docs/screens.md) | 画面一覧 |
| [docs/permissions.md](docs/permissions.md) | 権限一覧（機能×権限のマトリクス） |
| [docs/api.md](docs/api.md) | API一覧 |
| [docs/manual-user.md](docs/manual-user.md) | 操作マニュアル（店舗担当者・ベンダー担当者向け） |
| [docs/manual-admin.md](docs/manual-admin.md) | 管理者マニュアル |
| [docs/security.md](docs/security.md) | セキュリティ上の注意点 |
| [docs/audit-report.md](docs/audit-report.md) | 第三者監査の結果と是正内容 |
| [docs/roadmap.md](docs/roadmap.md) | 今後の拡張候補 |
| [docs/bms.md](docs/bms.md) | 流通BMS対応へ進む場合の追加課題一覧 |

---

## MVP完成条件の達成状況

| # | 完成条件 | 状況 | 確認方法 |
|---|---|---|---|
| 1 | 管理者・本部・店舗・ベンダーでログインできる | 実装済み | 動作確認用アカウントでログイン |
| 2 | 本部がベンダーを切り替えられる | 実装済み | 画面上部のベンダー選択 |
| 3 | 本部が店舗を切り替えられる | 実装済み | 画面上部の店舗選択 |
| 4 | 店舗は自店舗だけ閲覧できる | 実装済み | `test_店舗Aは店舗Bの発注を取得できない` |
| 5 | ベンダーは自ベンダーだけ閲覧できる | 実装済み | `test_ベンダーAはベンダーBのデータを取得できない` |
| 6 | 商品がベンダー別に自動振り分けされる | 実装済み | `test_商品はベンダー別に自動振り分けされる` |
| 7 | スマートフォンから発注登録できる | 実装済み | 発注入力画面（縦型カードUI） |
| 8 | スマートフォンから発注確定できる | 実装済み | 下部固定バーの「発注確定」 |
| 9 | ベンダーがスマートフォンから受注確認できる | 実装済み | 受注一覧の「受注確認」 |
| 10 | ベンダーが一部納品・欠品・代替提案を回答できる | 実装済み | `tests/test_vendor_responses.py` |
| 11 | 発注内容がリアルタイムで反映される | 実装済み | 20秒間隔の自動更新（入力中は中断しない） |
| 12 | 締め時間前は修正できる | 実装済み | `test_締め前は数量を変更できる` |
| 13 | 締め時間後は直接修正できない | 実装済み | `test_締め後は直接変更できない` |
| 14 | 締め後変更申請ができる | 実装済み | `test_締め後は変更申請になる` |
| 15 | 数量変更履歴が残る | 実装済み | `test_数量変更履歴が残る` |
| 16 | 操作ログが残る | 実装済み | `test_操作ログが残る` |
| 17 | 他ベンダーのデータへアクセスできない | 実装済み | `test_ベンダーAはURL変更でベンダーBの発注を開けない` |
| 18 | 他店舗のデータへアクセスできない | 実装済み | `test_店舗ユーザーはstore_idを指定しても他店舗を見られない` |
| 19 | Excel出力できる | 実装済み | 出力画面 / `tests/test_exports.py` |
| 20 | 自動テストがすべて成功する | 51件すべて成功 | `python -m pytest` |

### MVP対象外（仕様どおり未実装）

正式な流通BMS接続 / 請求処理 / 支払処理 / 基幹システム連携 / AI自動発注 /
プッシュ通知 / オフライン操作 / 電子契約 / 会計システム連携

### 既知の制約

- **PDF出力は「印刷用HTML」方式です。** ブラウザの印刷ダイアログから PDF として保存します。
  サーバー側で PDF バイナリを生成していないため、日本語フォントの同梱が不要で環境を選びません。
  バッチでの PDF ファイル生成が必要になった場合は WeasyPrint 等の追加が必要です。

---

## セキュリティ上の注意点

詳細は [docs/security.md](docs/security.md) を参照してください。要点のみ:

- パスワードは平文保存せず bcrypt でハッシュ化しています。
- 秘密鍵・DBパスワード・SMTPパスワードはすべて環境変数管理で、`.env` は Git 管理対象外です。
- **本番では `SECRET_KEY` を必ず変更し、`COOKIE_SECURE=true` と HTTPS を有効にしてください。**
- セッションは httpOnly Cookie（既定8時間）で、更新系リクエストには CSRF トークンを必須としています。
- SQLインジェクションは SQLAlchemy のパラメータバインドで、XSS はフロント側のエスケープ処理と
  Content-Security-Policy で対策しています。
- 権限チェックはすべての更新操作に入れており、権限外は 403 を返します。
- 取引履歴・操作ログは論理削除も含めて削除できません（削除APIを設けていません）。

---

## 今後の拡張候補

[docs/roadmap.md](docs/roadmap.md) を参照してください。優先度の高いものは次のとおりです。

1. PWA プッシュ通知（通知基盤は拡張しやすい構造にしてあります）
2. 商品の複数ベンダー対応（`product_vendors` テーブルは作成済み）
3. 納品実績の登録と検品
4. ログイン試行のレート制限（リバースプロキシ側での実装を推奨）
5. 流通BMS対応（[docs/bms.md](docs/bms.md)）
