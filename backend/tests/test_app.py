from __future__ import annotations

import os
import tempfile

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_tmpdir = tempfile.mkdtemp(prefix="igris-test-")
os.environ["DATA_DIR"] = _tmpdir
os.environ["SECRET_KEY"] = "test-secret-key-for-ci"
os.environ.pop("SETUP_TOKEN", None)

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def fresh_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _complete_setup(client: AsyncClient, with_smtp: bool = False) -> None:
    await client.post("/api/setup/step1", json={"app_name": "Igris"})
    await client.post(
        "/api/setup/step2",
        json={
            "username": "admin",
            "email": "admin@example.com",
            "password": "Str0ngPass!x",
            "confirm_password": "Str0ngPass!x",
        },
    )
    smtp = None
    if with_smtp:
        smtp = {
            "host": "smtp.example.com",
            "port": 587,
            "security": "STARTTLS",
            "username": "u",
            "password": "p",
            "from_name": "Igris",
            "from_email": "noreply@example.com",
        }
    await client.post("/api/setup/finish", json={"smtp": smtp})


class TestSetupLock:
    async def test_uninstalled_reports_state(self, client):
        r = await client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["installed"] is False
        r = await client.get("/api/setup/state")
        assert r.status_code == 200

    async def test_setup_404_after_install(self, client):
        await _complete_setup(client)
        r = await client.get("/api/setup/state")
        assert r.status_code == 404
        r = await client.post("/api/setup/step1", json={"app_name": "X"})
        assert r.status_code == 404


class TestSetupWizard:
    async def test_step2_password_mismatch(self, client):
        await client.post("/api/setup/step1", json={"app_name": "Igris"})
        r = await client.post(
            "/api/setup/step2",
            json={
                "username": "admin",
                "email": "a@b.com",
                "password": "Str0ngPass!x",
                "confirm_password": "Different!x",
            },
        )
        assert r.status_code == 422

    async def test_finish_autologin(self, client):
        await _complete_setup(client)
        r = await client.get("/api/auth/me")
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "admin"

    async def test_skip_smtp(self, client):
        await _complete_setup(client, with_smtp=False)
        r = await client.get("/api/health")
        assert r.json()["installed"] is True


class TestLogin:
    async def test_login_success(self, client):
        await _complete_setup(client)
        await client.post("/api/auth/logout")
        r = await client.post(
            "/api/auth/login",
            json={"username_or_email": "admin", "password": "Str0ngPass!x"},
        )
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "admin"

    async def test_login_failure_generic(self, client):
        await _complete_setup(client)
        await client.post("/api/auth/logout")
        r = await client.post(
            "/api/auth/login",
            json={"username_or_email": "admin", "password": "wrong"},
        )
        assert r.status_code == 401
        r = await client.post(
            "/api/auth/login",
            json={"username_or_email": "nobody", "password": "wrong"},
        )
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid credentials"

    async def test_login_lockout(self, client):
        await _complete_setup(client)
        await client.post("/api/auth/logout")
        for _ in range(5):
            await client.post(
                "/api/auth/login",
                json={"username_or_email": "admin", "password": "wrong"},
            )
        r = await client.post(
            "/api/auth/login",
            json={"username_or_email": "admin", "password": "Str0ngPass!x"},
        )
        assert r.status_code == 429

    async def test_logout_invalidates(self, client):
        await _complete_setup(client)
        r = await client.get("/api/auth/me")
        assert r.status_code == 200
        await client.post("/api/auth/logout")
        r = await client.get("/api/auth/me")
        assert r.status_code == 401


class TestPasswordReset:
    async def test_reset_flow(self, client, monkeypatch):
        await _complete_setup(client, with_smtp=True)
        await client.post("/api/auth/logout")

        from app.routers import auth as auth_router

        async def fake_send_email(**kwargs):
            pass

        monkeypatch.setattr(auth_router, "send_email", fake_send_email)

        r = await client.post(
            "/api/auth/forgot-password", json={"email": "admin@example.com"}
        )
        assert r.status_code == 200

        from sqlalchemy import select

        from app.models import ResetToken

        async with SessionLocal() as s:
            result = await s.execute(select(ResetToken))
            rt = result.scalars().first()
            assert rt is not None
            token = rt.id

        r = await client.post(
            "/api/auth/reset-password",
            json={
                "token": token,
                "password": "N3wPass!yyy",
                "confirm_password": "N3wPass!yyy",
            },
        )
        assert r.status_code == 200

        r = await client.post(
            "/api/auth/reset-password",
            json={
                "token": token,
                "password": "N3wPass!yyy",
                "confirm_password": "N3wPass!yyy",
            },
        )
        assert r.status_code == 400

        r = await client.post(
            "/api/auth/login",
            json={"username_or_email": "admin", "password": "N3wPass!yyy"},
        )
        assert r.status_code == 200

    async def test_reset_requires_smtp(self, client):
        await _complete_setup(client, with_smtp=False)
        r = await client.post(
            "/api/auth/forgot-password", json={"email": "admin@example.com"}
        )
        assert r.status_code == 400


class TestSmtpCrypto:
    async def test_smtp_password_encrypted(self, client):
        await _complete_setup(client, with_smtp=True)
        from app.services.auth import get_setting

        async with SessionLocal() as s:
            stored = await get_setting(s, "smtp_password")
        assert stored
        assert stored != "p"
        assert len(stored) > 10
