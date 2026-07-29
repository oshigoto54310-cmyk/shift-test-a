"""認証・セッションの回帰テスト。

第三者監査で、ログアウト後・パスワード変更後も発行済みトークンが使えることが判明した。
Cookie を消すだけではトークンを手元に持っている相手を止められないため、
サーバー側で失効させる仕組みを追加した。その再発防止として追加している。
"""
from __future__ import annotations

from datetime import timedelta

from app.database import SessionLocal
from app.models import User, utcnow
from app.security import verify_password

from .conftest import PASSWORD, make_client
from fastapi.testclient import TestClient
from app.main import app


def _bearer(token: str) -> TestClient:
    """Cookie ではなく Bearer でトークンだけを使うクライアント。"""
    client = TestClient(app)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _login_raw(email: str, password: str = PASSWORD):
    client = TestClient(app)
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    return client, res


# --------------------------------------------------------------------------
# セッション失効
# --------------------------------------------------------------------------
def test_ログアウト後は同じトークンを再利用できない():
    client, res = _login_raw("sessiona@test.invalid")
    assert res.status_code == 200
    token = client.cookies.get("order_session")
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")

    stolen = _bearer(token)
    assert stolen.get("/api/auth/me").status_code == 200, "前提: ログアウト前は使える"

    assert client.post("/api/auth/logout").status_code == 200
    assert stolen.get("/api/auth/me").status_code == 401, "ログアウト後もトークンが有効になっている"
    assert stolen.get("/api/orders").status_code == 401


def test_パスワード変更で他端末のセッションが失効する():
    client, _ = _login_raw("sessionb@test.invalid")
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    other, _ = _login_raw("sessionb@test.invalid")
    other_token = other.cookies.get("order_session")

    assert _bearer(other_token).get("/api/auth/me").status_code == 200

    res = client.post("/api/auth/password", json={
        "current_password": PASSWORD, "new_password": "Changed12345!",
    })
    assert res.status_code == 200
    assert _bearer(other_token).get("/api/auth/me").status_code == 401, "旧セッションが残っている"

    # 変更した本人は続けて操作できる（新しいトークンが発行される）
    assert client.get("/api/auth/me").status_code == 200


def test_パスワード再設定で既存セッションが失効する():
    client, _ = _login_raw("sessionc@test.invalid")
    token = client.cookies.get("order_session")
    assert _bearer(token).get("/api/auth/me").status_code == 200

    anon = TestClient(app)
    anon.post("/api/auth/password-reset/request", json={"email": "sessionc@test.invalid"})
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "sessionc@test.invalid").first()
        reset_token = user.password_reset_token
    finally:
        db.close()

    res = anon.post("/api/auth/password-reset/confirm", json={
        "token": reset_token, "new_password": "Reset12345!",
    })
    assert res.status_code == 200
    assert _bearer(token).get("/api/auth/me").status_code == 401


def test_再設定トークンは1度しか使えない():
    anon = TestClient(app)
    anon.post("/api/auth/password-reset/request", json={"email": "sessiond@test.invalid"})
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "sessiond@test.invalid").first()
        token = user.password_reset_token
    finally:
        db.close()

    assert anon.post("/api/auth/password-reset/confirm",
                     json={"token": token, "new_password": "First12345!"}).status_code == 200
    second = anon.post("/api/auth/password-reset/confirm",
                       json={"token": token, "new_password": "Second12345!"})
    assert second.status_code == 400, "再設定トークンを使い回せてしまう"


def test_期限切れの再設定トークンは使えない():
    anon = TestClient(app)
    anon.post("/api/auth/password-reset/request", json={"email": "sessione@test.invalid"})
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "sessione@test.invalid").first()
        token = user.password_reset_token
        user.password_reset_expires = utcnow() - timedelta(minutes=1)
        db.add(user)
        db.commit()
    finally:
        db.close()
    res = anon.post("/api/auth/password-reset/confirm",
                    json={"token": token, "new_password": "Expired12345!"})
    assert res.status_code == 400


def test_権限変更で既存セッションが失効する(admin):
    client, _ = _login_raw("sessionf@test.invalid")
    token = client.cookies.get("order_session")
    assert _bearer(token).get("/api/auth/me").status_code == 200

    users = admin.get("/api/users").json()
    target = next(u for u in users if u["email"] == "sessionf@test.invalid")
    stores = admin.get("/api/stores").json()
    other_store = next(s["id"] for s in stores if s["id"] != target["store_id"])

    res = admin.put(f"/api/users/{target['id']}", json={
        "email": target["email"], "name": target["name"], "role_code": "STORE",
        "store_id": other_store, "vendor_id": None, "is_active": True,
    })
    assert res.status_code == 200
    assert _bearer(token).get("/api/auth/me").status_code == 401, \
        "所属変更後も旧権限のセッションが使えてしまう"


def test_停止されたユーザーの既存セッションは遮断される(admin):
    client, _ = _login_raw("sessiong@test.invalid")
    assert client.get("/api/orders").status_code == 200

    users = admin.get("/api/users").json()
    target = next(u for u in users if u["email"] == "sessiong@test.invalid")
    assert admin.delete(f"/api/users/{target['id']}").status_code == 200

    assert client.get("/api/orders").status_code in (401, 403)


# --------------------------------------------------------------------------
# パスワード保管とログイン制御
# --------------------------------------------------------------------------
def test_パスワードは平文保存されない():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for user in users:
            assert user.password_hash != PASSWORD
            assert PASSWORD not in user.password_hash
            # bcrypt のハッシュ形式であること
            assert user.password_hash.startswith("$2b$") or user.password_hash.startswith("$2a$")
        target = next(u for u in users if u.email == "storea@test.invalid")
        assert verify_password(PASSWORD, target.password_hash)
        assert not verify_password("wrong-password", target.password_hash)
    finally:
        db.close()


def test_存在しないユーザーと誤パスワードで応答が変わらない():
    _, missing = _login_raw("nobody@test.invalid", "whatever123")
    _, wrong = _login_raw("storea@test.invalid", "wrong-password-here")
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"], \
        "応答の差からアカウントの存在を推測できてしまう"


def test_パスワード再設定はアカウントの有無を漏らさない():
    anon = TestClient(app)
    exists = anon.post("/api/auth/password-reset/request", json={"email": "storea@test.invalid"})
    missing = anon.post("/api/auth/password-reset/request", json={"email": "nobody@test.invalid"})
    assert exists.status_code == missing.status_code == 200
    assert exists.json() == missing.json()


def test_改ざんされたトークンは受け付けない():
    client, _ = _login_raw("sessionh@test.invalid")
    token = client.cookies.get("order_session")
    head, payload, sig = token.split(".")
    forged = f"{head}.{payload}.{'A' * len(sig)}"
    assert _bearer(forged).get("/api/auth/me").status_code == 401
    assert _bearer("not-a-jwt").get("/api/auth/me").status_code == 401
