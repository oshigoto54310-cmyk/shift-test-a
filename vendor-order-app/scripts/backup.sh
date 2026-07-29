#!/usr/bin/env bash
#
# データベースのバックアップを取得する。
#
#   ./scripts/backup.sh                 # ./backups へ出力
#   BACKUP_DIR=/mnt/nas ./scripts/backup.sh
#
# cron 例（毎日 2:30 に取得）:
#   30 2 * * * cd /opt/vendor-order-app && ./scripts/backup.sh >> /var/log/order-backup.log 2>&1
#
# 注意: バックアップには取引情報が含まれます。保管先のアクセス権を制限してください。

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M%S)"

# .env があれば読み込む（POSTGRES_USER / POSTGRES_DB を使う）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

PG_USER="${POSTGRES_USER:-order_user}"
PG_DB="${POSTGRES_DB:-order_app}"

mkdir -p "$BACKUP_DIR"
OUT="$BACKUP_DIR/${PG_DB}_${STAMP}.sql.gz"

echo "[$(date '+%F %T')] バックアップを開始します -> $OUT"

if ! docker compose ps db --status running >/dev/null 2>&1; then
  echo "エラー: db コンテナが起動していません。'docker compose up -d db' を実行してください。" >&2
  exit 1
fi

# --clean --if-exists を付けてリストア時に既存オブジェクトを置き換えられるようにする
docker compose exec -T db pg_dump \
  --username="$PG_USER" \
  --dbname="$PG_DB" \
  --clean --if-exists --no-owner --no-privileges \
  | gzip -9 > "$OUT.tmp"

# 中身が空でないことを確認してから正式なファイル名にする（失敗した空ファイルを残さない）
if [ ! -s "$OUT.tmp" ]; then
  echo "エラー: バックアップが空です。処理を中止します。" >&2
  rm -f "$OUT.tmp"
  exit 1
fi
mv "$OUT.tmp" "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo "[$(date '+%F %T')] 完了: $OUT ($SIZE)"

# 世代管理
DELETED="$(find "$BACKUP_DIR" -name "${PG_DB}_*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete | wc -l)"
if [ "$DELETED" -gt 0 ]; then
  echo "$RETENTION_DAYS 日より古いバックアップを $DELETED 件削除しました"
fi

echo "現在の保有数: $(find "$BACKUP_DIR" -name "${PG_DB}_*.sql.gz" | wc -l) 件"
