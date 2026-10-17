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

__all__ = ["fresh_db", "client", "SessionLocal", "_complete_setup"]


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
