#!/usr/bin/env bash
#
# バックアップからデータベースを復元する。
#
#   ./scripts/restore.sh ./backups/order_app_20260729_023000.sql.gz
#
# 警告: 現在のデータは失われます。実行前に必ず現状のバックアップを取ってください。
#       本番で実行する場合はアプリを停止してから行ってください。

set -euo pipefail

cd "$(dirname "$0")/.."

FILE="${1:-}"
if [ -z "$FILE" ]; then
  echo "使い方: $0 <バックアップファイル(.sql.gz)>" >&2
  echo "" >&2
  echo "利用可能なバックアップ:" >&2
  ls -1t ./backups/*.sql.gz 2>/dev/null | head -20 >&2 || echo "  (なし)" >&2
  exit 1
fi

if [ ! -f "$FILE" ]; then
  echo "エラー: ファイルが見つかりません: $FILE" >&2
  exit 1
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PG_USER="${POSTGRES_USER:-order_user}"
PG_DB="${POSTGRES_DB:-order_app}"

echo "============================================================"
echo " 復元元 : $FILE"
echo " 復元先 : $PG_DB (ユーザー: $PG_USER)"
echo "============================================================"
echo ""
echo "警告: 現在のデータベースの内容は失われます。"
printf "続行するには 'restore' と入力してください: "
read -r ANSWER
if [ "$ANSWER" != "restore" ]; then
  echo "中止しました。"
  exit 1
fi

if ! docker compose ps db --status running >/dev/null 2>&1; then
  echo "エラー: db コンテナが起動していません。'docker compose up -d db' を実行してください。" >&2
  exit 1
fi

# 復元前に念のため現状を退避しておく
SAFETY="./backups/pre_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
mkdir -p ./backups
echo "復元前の状態を $SAFETY へ退避します..."
docker compose exec -T db pg_dump --username="$PG_USER" --dbname="$PG_DB" \
  --clean --if-exists --no-owner --no-privileges | gzip -9 > "$SAFETY" || {
    echo "警告: 退避に失敗しました。それでも続行する場合は Ctrl-C で中止してください。" >&2
    sleep 5
  }

echo "アプリを停止します..."
docker compose stop app notifier >/dev/null 2>&1 || true

echo "復元中..."
gunzip -c "$FILE" | docker compose exec -T db psql \
  --username="$PG_USER" --dbname="$PG_DB" --set ON_ERROR_STOP=on --quiet

echo "マイグレーションの状態を確認します..."
docker compose run --rm app alembic upgrade head

echo "アプリを再起動します..."
docker compose up -d app notifier

echo ""
echo "復元が完了しました。"
echo "退避ファイル: $SAFETY （問題なければ削除してください）"
