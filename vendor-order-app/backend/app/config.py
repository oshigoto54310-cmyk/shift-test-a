"""アプリケーション設定。秘密情報はすべて環境変数から読み込む。"""
from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基本
    app_name: str = "ベンダー別発注管理"
    environment: str = "development"
    debug: bool = False

    # DB: 開発は SQLite、本番は PostgreSQL（DATABASE_URL を差し替えるだけで移行できる）
    database_url: str = "sqlite:///./order_app.db"

    # 認証
    secret_key: str = "CHANGE_ME_IN_PRODUCTION_この値は必ず環境変数で上書きすること"
    jwt_algorithm: str = "HS256"
    session_minutes: int = 480          # セッション有効期限（分）
    max_login_failures: int = 5         # ロックまでのログイン失敗回数
    lock_minutes: int = 15              # 一時ロック時間（分）

    # Cookie / HTTPS
    cookie_name: str = "order_session"
    csrf_cookie_name: str = "csrf_token"
    cookie_secure: bool = False         # 本番（HTTPS）では true
    cookie_samesite: str = "lax"

    # CORS（フロントを別ホストで動かす場合に設定）
    cors_origins: str = ""

    # 締め時間のシステム標準値（優先順位: 商品別 > ベンダー別 > システム標準）
    default_rough_days_before: int = 3       # 概算締め: 納品日の3日前
    default_final_days_before: int = 1       # 最終締め: 納品日の前日
    default_final_time: str = "12:00"        # 最終締め時刻
    default_reply_days_before: int = 1       # ベンダー回答期限: 納品日の前日
    default_reply_time: str = "15:00"        # ベンダー回答期限時刻

    # メール通知（未設定時はDBへの記録のみ行い送信はスキップする）
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "no-reply@example.invalid"
    smtp_tls: bool = True
    mail_enabled: bool = False

    # 異常数量警告のしきい値
    abnormal_qty_threshold: int = 1000

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


APP_TZ = ZoneInfo("Asia/Tokyo")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
