from __future__ import annotations

import pytest  # noqa: F401
from httpx import AsyncClient

from tests.test_app import _complete_setup

FYERS_PAYLOAD = {
    "provider": "fyers",
    "label": "Fyers main",
    "app_id": "APP123",
    "app_secret": "s3cret",
}
GROWW_PAYLOAD = {
    "provider": "groww",
    "label": "Groww main",
    "app_id": "groww_key_1",
    "app_secret": "JBSWY3DPEHPK3PXP",
}


async def _make(client: AsyncClient, payload: dict | None = None) -> str:
    r = await client.post("/api/connections", json=payload or FYERS_PAYLOAD)
    assert r.status_code == 200, r.text
    lst = (await client.get("/api/connections")).json()
    return lst[-1]["id"]


class TestAuthRequired:
    async def test_tc020_unauthenticated_get_401(self, client):
        r = await client.get("/api/connections")
        assert r.status_code == 401

    async def test_tc020_unauthenticated_post_401(self, client):
        r = await client.post("/api/connections", json=FYERS_PAYLOAD)
        assert r.status_code == 401


class TestCrud:
    async def test_tc021_create_fyers_missing_secret_rejected(self, client):
        await _complete_setup(client)
        r = await client.post(
            "/api/connections",
            json={"provider": "fyers", "app_id": "APP1", "app_secret": ""},
        )
        assert r.status_code == 422

    async def test_tc022_create_and_list(self, client):
        await _complete_setup(client)
        await _make(client)
        r = await client.get("/api/connections")
        body = r.json()
        assert len(body) == 1
        c = body[0]
        assert c["provider"] == "fyers"
        assert c["status"] == "never_authed"
        assert "get_profile" in c["tools"]
        assert "credentials" not in c and "app_secret" not in c

    async def test_tc023_credentials_encrypted_at_rest(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        from app.database import SessionLocal
        from app.models import Connection
        from app.services import connections as svc

        async with SessionLocal() as s:
            conn = await s.get(Connection, conn_id)
            assert conn.credentials
            assert "s3cret" not in conn.credentials  # ciphertext, not plaintext
            assert svc.load_credentials(conn)["app_secret"] == "s3cret"

    async def test_tc024_patch_reauth_time(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.patch(f"/api/connections/{conn_id}", json={"reauth_time": "09:15"})
        assert r.status_code == 200
        body = (await client.get("/api/connections")).json()
        assert body[0]["reauth_time"] == "09:15"
        r = await client.patch(f"/api/connections/{conn_id}", json={"reauth_time": "99:99"})
        assert r.status_code == 422

    async def test_tc025_delete(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.delete(f"/api/connections/{conn_id}")
        assert r.status_code == 200
        assert (await client.get("/api/connections")).json() == []

    async def test_tc025b_delete_missing_404(self, client):
        await _complete_setup(client)
        r = await client.delete("/api/connections/nope")
        assert r.status_code == 404


class TestFyersAuth:
    async def test_tc026_auth_url_contains_endpoint_and_state(self, client, monkeypatch):
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(f"/api/connections/{conn_id}/auth-url")
        assert r.status_code == 200
        data = r.json()
        assert "generate-authcode" in data["url"]
        assert f"state={conn_id}" in data["url"]
        assert "client_id=APP123" in data["url"]
        assert isinstance(data["manual"], bool)

    async def test_tc027_complete_auth_success(self, client, monkeypatch):
        from datetime import datetime, timedelta, timezone

        import app.services.brokers.fyers as fb

        async def fake_exchange(app_id, app_secret, code):
            assert app_id == "APP123" and app_secret == "s3cret" and code == "CODE1"
            return {
                "access_token": "tok-abc",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            }

        monkeypatch.setattr(fb, "exchange_code", fake_exchange)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(
            f"/api/connections/{conn_id}/complete-auth", json={"code": "CODE1"}
        )
        assert r.status_code == 200
        c = (await client.get("/api/connections")).json()[0]
        assert c["status"] == "connected"
        assert c["expires_at"] is not None

    async def test_tc028_complete_auth_failure_marks_error(self, client, monkeypatch):
        import app.services.brokers.fyers as fb

        async def fake_exchange(app_id, app_secret, code):
            raise RuntimeError("invalid code")

        monkeypatch.setattr(fb, "exchange_code", fake_exchange)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(
            f"/api/connections/{conn_id}/complete-auth", json={"code": "BAD"}
        )
        assert r.status_code == 400
        c = (await client.get("/api/connections")).json()[0]
        assert c["status"] == "error"
        assert "invalid code" in c["last_error"]

    async def test_tc032_callback_unknown_state(self, client):
        await _complete_setup(client)
        r = await client.get(
            "/api/connections/fyers/callback", params={"code": "X", "state": "missing"}
        )
        assert r.status_code == 200
        assert "oauth" in r.json()["detail"] or "fail" in r.json()["detail"]


class TestGrowwAuth:
    async def test_tc029_groww_connect_success(self, client, monkeypatch):
        from datetime import datetime, timedelta, timezone

        import app.services.brokers.groww as gb

        async def fake_connect(api_key, totp_secret):
            assert api_key == "groww_key_1"
            assert totp_secret == "JBSWY3DPEHPK3PXP"
            return {
                "access_token": "groww-tok",
                "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
            }

        monkeypatch.setattr(gb, "connect", fake_connect)
        await _complete_setup(client)
        conn_id = await _make(client, GROWW_PAYLOAD)
        r = await client.post(f"/api/connections/{conn_id}/connect-groww")
        assert r.status_code == 200
        c = (await client.get("/api/connections")).json()[0]
        assert c["status"] == "connected"

    async def test_tc029b_groww_connect_failure(self, client, monkeypatch):
        import app.services.brokers.groww as gb

        async def fake_connect(api_key, totp_secret):
            raise RuntimeError("TOTP rejected")

        monkeypatch.setattr(gb, "connect", fake_connect)
        await _complete_setup(client)
        conn_id = await _make(client, GROWW_PAYLOAD)
        r = await client.post(f"/api/connections/{conn_id}/connect-groww")
        assert r.status_code == 400
        c = (await client.get("/api/connections")).json()[0]
        assert c["status"] == "error"

    async def test_tc030_test_endpoint_fyers(self, client, monkeypatch):
        import app.services.brokers.fyers as fb

        async def fake_test(app_id, token):
            return (True, "OK · 42ms")

        monkeypatch.setattr(fb, "test_connection", fake_test)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(f"/api/connections/{conn_id}/test")
        assert r.status_code == 200
        assert r.json() == {"success": True, "message": "OK · 42ms"}


class TestConfig:
    async def test_tc031_config_shape(self, client):
        await _complete_setup(client)
        r = await client.get("/api/connections/config")
        assert r.status_code == 200
        body = r.json()
        assert body["manual_flow"] in (True, False)
        assert "redirect_uri" in body
        assert "fyers" in body["help"] and "groww" in body["help"]
        assert "{redirect}" in body["help"]["fyers"]["steps"][2]
        assert "place_order" in body["tools"]["fyers"]
        assert "get_ltp" in body["tools"]["groww"]


class TestScheduler:
    async def test_tc033_due_for_reauth_logic(self):
        from datetime import datetime, timedelta, timezone

        from app.models import Connection
        from app.services.scheduler import IST, _due_for_reauth

        def conn(reauth_time: str, last_reauth_at=None) -> Connection:
            return Connection(
                id="x",
                user_id=1,
                provider="groww",
                label="t",
                reauth_time=reauth_time,
                last_reauth_at=last_reauth_at,
            )

        now_ist = datetime.now(timezone.utc).astimezone(IST)
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)

        # scheduled time already passed today, last run yesterday -> due
        past = (now_ist - timedelta(hours=1)).strftime("%H:%M")
        assert _due_for_reauth(conn(past, last_reauth_at=yesterday)) is True
        # already ran today -> not due
        assert _due_for_reauth(conn(past, last_reauth_at=datetime.now(timezone.utc))) is False
        # scheduled later today -> not due
        future = (now_ist + timedelta(hours=2)).strftime("%H:%M")
        assert _due_for_reauth(conn(future, last_reauth_at=yesterday)) is False

    async def test_tc033b_due_never_ran_after_time(self):
        from datetime import datetime, timedelta, timezone

        from app.models import Connection
        from app.services.scheduler import IST, _due_for_reauth

        now_ist = datetime.now(timezone.utc).astimezone(IST)
        past = (now_ist - timedelta(minutes=30)).strftime("%H:%M")
        c = Connection(
            id="x",
            user_id=1,
            provider="fyers",
            label="t",
            reauth_time=past,
            last_reauth_at=None,
        )
        assert _due_for_reauth(c) is True

    async def test_tc082_groww_token_expiry_is_0600_ist(self):
        """Groww tokens die daily 06:00 IST — stored expiry must match reality."""
        from datetime import datetime, timedelta, timezone

        from app.services.brokers.groww import next_token_expiry

        ist = timezone(timedelta(hours=5, minutes=30))
        # before 06:00 IST -> expiry is 06:00 IST today
        before = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)  # 05:30 IST
        exp = next_token_expiry(before)
        assert exp > before
        assert exp.astimezone(ist).strftime("%H:%M") == "06:00"
        # after 06:00 IST -> expiry is 06:00 IST tomorrow
        after = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
        exp2 = next_token_expiry(after)
        assert after < exp2 < after + timedelta(days=1)
        assert exp2.astimezone(ist).strftime("%H:%M") == "06:00"


class TestGrowwTotpQr:
    def test_extract_totp_secret_from_otpauth(self):
        from app.services.connections import extract_totp_secret

        qr = "otpauth://totp/Groww:api?secret=JBSWY3DPEHPK3PXP&issuer=Groww&digits=6"
        assert extract_totp_secret(qr) == "JBSWY3DPEHPK3PXP"

    def test_extract_totp_secret_plain_base32(self):
        from app.services.connections import extract_totp_secret

        assert extract_totp_secret(" jbsw y3dp ehpk 3pxp ") == "JBSWY3DPEHPK3PXP"

    def test_extract_totp_secret_invalid(self):
        import pytest

        from app.services.connections import extract_totp_secret

        with pytest.raises(ValueError):
            extract_totp_secret("not-a-secret!")

    async def test_tc039_create_groww_with_qr_payload(self, client):
        await _complete_setup(client)
        r = await client.post(
            "/api/connections",
            json={
                "provider": "groww",
                "label": "Groww QR",
                "app_id": "totp-token-1",
                "app_secret": "",
                "totp_qr": "otpauth://totp/Groww:api?secret=JBSWY3DPEHPK3PXP&issuer=Groww",
            },
        )
        assert r.status_code == 200, r.text
        c = (await client.get("/api/connections")).json()[0]
        assert c["app_id"] == "totp-t…en-1"  # masked, full token never returned
        from app.database import SessionLocal
        from app.models import Connection
        from app.services import connections as svc

        async with SessionLocal() as s:
            conn = await s.get(Connection, c["id"])
            assert svc.load_credentials(conn)["totp_secret"] == "JBSWY3DPEHPK3PXP"

    async def test_tc039b_groww_requires_token_and_secret(self, client):
        await _complete_setup(client)
        r = await client.post(
            "/api/connections",
            json={"provider": "groww", "app_id": "", "app_secret": "", "totp_qr": ""},
        )
        assert r.status_code == 422
        r = await client.post(
            "/api/connections",
            json={"provider": "groww", "app_id": "t", "app_secret": "", "totp_qr": ""},
        )
        assert r.status_code == 422
        r = await client.post(
            "/api/connections",
            json={"provider": "groww", "app_id": "t", "app_secret": "", "totp_qr": "garbage"},
        )
        assert r.status_code == 422


class TestSecurityAndGrowwTest:
    def test_mask_secret(self):
        from app.services.connections import mask_secret

        assert mask_secret("") == ""
        assert mask_secret("short") == "••••••"
        m = mask_secret("eyJraWQiOiJaTUtjVXciLCJhbGciOiJFUzI1NiJ9")
        assert m.startswith("eyJraW") and m.endswith("NiJ9") and "…" in m
        assert "TUtjVXci" not in m

    async def test_tc040_list_does_not_leak_full_token(self, client):
        await _complete_setup(client)
        await _make(client, GROWW_PAYLOAD)
        body = (await client.get("/api/connections")).json()[0]
        assert body["app_id"] == "groww_…ey_1"  # masked: groww_key_1
        assert "groww_key_1" not in (await client.get("/api/connections")).text

    async def test_tc041_groww_test_success_without_profile_fields(self, monkeypatch):
        import app.services.brokers.groww as gb

        class FakeGroww:
            def get_user_profile(self):
                return {"user_id": "abc", "name": "x"}  # no status/payload keys

        monkeypatch.setattr(gb, "client", lambda token: FakeGroww())
        ok, msg = await gb.test_connection("tok")
        assert ok and msg.startswith("OK")

    async def test_tc041b_groww_test_failure_message(self, monkeypatch):
        import app.services.brokers.groww as gb

        class FakeGroww:
            def get_user_profile(self):
                raise RuntimeError("Groww API Error 400: Bad Request")

        monkeypatch.setattr(gb, "client", lambda token: FakeGroww())
        ok, msg = await gb.test_connection("tok")
        assert not ok and "Bad Request" in msg


class TestFyersExpiry:
    def test_tc042_token_expires_next_630am_ist(self):
        from datetime import datetime, timedelta, timezone

        from app.services.brokers.fyers import IST, next_token_expiry

        # 05:00 IST on Oct 17 -> expires same day 06:30 IST
        before = datetime(2026, 10, 17, 5, 0, tzinfo=IST)
        exp = next_token_expiry(before)
        assert exp == datetime(2026, 10, 17, 6, 30, tzinfo=IST).astimezone(timezone.utc)
        # 07:00 IST on Oct 17 -> expires next day 06:30 IST
        after = datetime(2026, 10, 17, 7, 0, tzinfo=IST)
        exp2 = next_token_expiry(after)
        assert exp2 == datetime(2026, 10, 18, 6, 30, tzinfo=IST).astimezone(timezone.utc)
        # always in the future relative to the evaluated moment (date-independent)
        assert exp > before.astimezone(timezone.utc)
        assert exp2 > after.astimezone(timezone.utc)
        # default call (wall clock now) is always in the future
        assert next_token_expiry() > datetime.now(timezone.utc)


class TestFyersCallbackParams:
    async def test_tc043_callback_uses_auth_code_param(self, client, monkeypatch):
        from datetime import datetime, timedelta, timezone

        import app.services.brokers.fyers as fb

        seen = {}

        async def fake_exchange(app_id, app_secret, code):
            seen["code"] = code
            return {
                "access_token": "tok",
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=12),
            }

        monkeypatch.setattr(fb, "exchange_code", fake_exchange)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.get(
            "/api/connections/fyers/callback",
            params={
                "s": "ok",
                "code": "200",
                "auth_code": "HEADER.PAYLOAD.SIG",
                "state": conn_id,
            },
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert seen["code"] == "HEADER.PAYLOAD.SIG"  # not "200"
        c = (await client.get("/api/connections")).json()[0]
        assert c["status"] == "connected"
