from __future__ import annotations

from httpx import AsyncClient

from tests.test_app import _complete_setup

OPENAI_PAYLOAD = {
    "provider": "openai",
    "label": "OpenAI main",
    "api_key": "sk-test-1234567890abcdef",
    "model": "gpt-4o-mini",
}


async def _make(client: AsyncClient, payload: dict | None = None) -> str:
    r = await client.post("/api/llm", json=payload or OPENAI_PAYLOAD)
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestLlmCrud:
    async def test_tc050_unauthenticated_401(self, client):
        assert (await client.get("/api/llm")).status_code == 401
        assert (await client.post("/api/llm", json=OPENAI_PAYLOAD)).status_code == 401

    async def test_tc051_create_and_list_masks_key(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        body = (await client.get("/api/llm")).json()
        assert len(body) == 1
        row = body[0]
        assert row["id"] == conn_id
        assert row["provider"] == "openai"
        assert row["model"] == "gpt-4o-mini"
        assert row["api_key_masked"].startswith("sk-te") and "…" in row["api_key_masked"]
        assert "sk-test-1234567890abcdef" not in (await client.get("/api/llm")).text

    async def test_tc052_patch_model(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.patch(f"/api/llm/{conn_id}", json={"model": "gpt-4o"})
        assert r.status_code == 200
        body = (await client.get("/api/llm")).json()[0]
        assert body["model"] == "gpt-4o"

    async def test_tc053_delete(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        assert (await client.delete(f"/api/llm/{conn_id}")).status_code == 200
        assert (await client.get("/api/llm")).json() == []

    async def test_tc054_custom_requires_base_url(self, client):
        await _complete_setup(client)
        r = await client.post(
            "/api/llm",
            json={"provider": "custom", "api_key": "k", "model": "m", "base_url": ""},
        )
        assert r.status_code == 422


class TestLlmConfig:
    async def test_tc055_config_lists_providers(self, client):
        await _complete_setup(client)
        body = (await client.get("/api/llm/config")).json()
        ids = {p["id"] for p in body["providers"]}
        assert {"openai", "anthropic", "gemini", "groq", "openrouter", "custom"} <= ids
        openai = next(p for p in body["providers"] if p["id"] == "openai")
        assert "gpt-4o" in openai["models"]


class TestLlmTestEndpoint:
    async def test_tc056_test_success_mocked(self, client, monkeypatch):
        import app.services.llm as llm_svc

        async def fake_test(row, api_key):
            assert api_key == "sk-test-1234567890abcdef"
            return (True, "OK · gpt-4o-mini · 120ms")

        monkeypatch.setattr(llm_svc, "test_connection", fake_test)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(f"/api/llm/{conn_id}/test")
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_tc057_test_failure_mocked(self, client, monkeypatch):
        import app.services.llm as llm_svc

        async def fake_test(row, api_key):
            return (False, "Incorrect API key provided")

        monkeypatch.setattr(llm_svc, "test_connection", fake_test)
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post(f"/api/llm/{conn_id}/test")
        assert r.json() == {"success": False, "message": "Incorrect API key provided"}


class TestLoadModels:
    async def test_tc071_models_static_fallback_no_key(self, client):
        await _complete_setup(client)
        r = await client.post("/api/llm/models", json={"provider": "groq", "api_key": ""})
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "groq"
        assert body["models"]  # static fallback list
        assert body["source"].startswith("static")

    async def test_tc072_models_for_saved_connection(self, client):
        await _complete_setup(client)
        conn_id = await _make(client)
        r = await client.post("/api/llm/models", json={"conn_id": conn_id})
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "openai"
        assert body["models"]  # api or static fallback — never empty
        assert "gpt-4o" in body["models"]

    async def test_tc073_models_unknown_provider_422(self, client):
        await _complete_setup(client)
        r = await client.post("/api/llm/models", json={"provider": "nope", "api_key": "x"})
        assert r.status_code == 422
