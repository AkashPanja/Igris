from __future__ import annotations

import json

from httpx import AsyncClient

from tests.test_app import _complete_setup, SessionLocal


async def _make_llm(client: AsyncClient) -> None:
    r = await client.post("/api/llm", json={
        "provider": "groq", "label": "test", "api_key": "gsk_test", "model": "llama-3.3-70b-versatile",
    })
    assert r.status_code == 200


async def _force_market_open(monkeypatch) -> None:
    import app.services.agent.trading as tr

    monkeypatch.setattr(tr, "is_market_hours", lambda *a, **k: True)


class TestRules:
    async def test_tc060_defaults_and_get(self, client):
        await _complete_setup(client)
        r = await client.get("/api/agent/rules")
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "paper"
        assert body["autonomy"] == "paper"
        assert body["kill_switch"] is False
        assert body["hard_caps"]["max_risk_per_trade_pct"] == 2.0

    async def test_tc061_patch_clamped_to_hard_caps(self, client):
        await _complete_setup(client)
        r = await client.patch("/api/agent/rules", json={"risk_per_trade_pct": 9.9, "max_open_positions": 50})
        assert r.status_code == 200
        assert "clamped" in r.json()["detail"]
        body = (await client.get("/api/agent/rules")).json()
        assert body["risk_per_trade_pct"] == 2.0
        assert body["max_open_positions"] == 5

    async def test_tc062_mode_live_requires_typing_live(self, client):
        await _complete_setup(client)
        r = await client.post("/api/agent/mode", json={"mode": "live", "confirm": "yes"})
        assert r.status_code == 422
        r = await client.post("/api/agent/mode", json={"mode": "live", "confirm": "LIVE"})
        assert r.status_code == 200
        body = (await client.get("/api/agent/rules")).json()
        assert body["mode"] == "live"
        assert body["autonomy"] == "live_approve"
        r = await client.post("/api/agent/mode", json={"mode": "paper"})
        assert r.status_code == 200
        body = (await client.get("/api/agent/rules")).json()
        assert body["mode"] == "paper" and body["autonomy"] == "paper"

    async def test_tc063_update_rule_tool_needs_confirmation(self, client):
        await _complete_setup(client)
        async with SessionLocal() as session:
            from app.models import User
            from app.services.agent import tools as T
            from sqlalchemy import select

            user = (await session.execute(select(User))).scalars().first()
            result = await T.execute_tool(session, user, "update_rule", {"changes": {"risk_per_trade_pct": 0.5}})
            assert result["status"] == "needs_confirmation"
            token = result["token"]
            r = await client.post("/api/agent/confirm", json={"token": token})
            assert r.status_code == 200
            assert r.json()["status"] == "updated"
        body = (await client.get("/api/agent/rules")).json()
        assert body["risk_per_trade_pct"] == 0.5
        # double-use rejected
        r = await client.post("/api/agent/confirm", json={"token": token})
        assert r.status_code == 200 and "error" in r.json()


class TestPaperTrading:
    async def test_tc064_propose_trade_paper_fill_and_notify_long(self, client, monkeypatch):
        await _complete_setup(client)
        await _force_market_open(monkeypatch)
        async with SessionLocal() as session:
            from app.models import User
            from app.services.agent import tools as T
            from sqlalchemy import select

            user = (await session.execute(select(User))).scalars().first()
            result = await T.execute_tool(session, user, "propose_trade", {
                "symbol": "NSE:RELIANCE-EQ", "side": "BUY", "instrument": "equity_intraday",
                "entry": 1000, "stop": 990, "target": 1020, "rationale": "test",
            })
            assert result["status"] == "filled_paper", result
            trade = result["trade"]
            assert trade["mode"] == "paper"
            assert trade["is_long"] is True
            assert trade["qty"] >= 1  # sized from capital 100000 * 1% / 10
        trades = (await client.get("/api/agent/trades")).json()
        assert len(trades) == 1 and trades[0]["status"] == "open"
        notifs = (await client.get("/api/agent/notifications")).json()
        assert any(n["kind"] == "long_trade" for n in notifs)

    async def test_tc065_propose_vetoed_without_stop(self, client, monkeypatch):
        await _complete_setup(client)
        await _force_market_open(monkeypatch)
        async with SessionLocal() as session:
            from app.models import User
            from app.services.agent import tools as T
            from sqlalchemy import select

            user = (await session.execute(select(User))).scalars().first()
            result = await T.execute_tool(session, user, "propose_trade", {
                "symbol": "NSE:RELIANCE-EQ", "side": "BUY", "instrument": "equity_intraday",
                "entry": 1000, "stop": 0, "target": 1020,
            })
            assert result["status"] == "vetoed"
            assert "stop" in result["reason"].lower()

    async def test_tc066_costs_and_close_pnl(self, client, monkeypatch):
        from app.services.agent import trading as tr

        assert tr.compute_costs("equity_intraday", "BUY", 100, 1000) > 0
        px, slip = tr.apply_slippage("equity_intraday", "BUY", 1000)
        assert px > 1000 and slip > 0

        await _complete_setup(client)
        await _force_market_open(monkeypatch)
        async with SessionLocal() as session:
            from app.models import User
            from app.services.agent import tools as T
            from sqlalchemy import select

            user = (await session.execute(select(User))).scalars().first()
            result = await T.execute_tool(session, user, "propose_trade", {
                "symbol": "NSE:RELIANCE-EQ", "side": "BUY", "instrument": "equity_intraday",
                "entry": 1000, "stop": 990, "target": 1020,
            })
            trade_id = result["trade"]["id"]
            trade = await session.get(tr.Trade, trade_id)
            await tr.close_trade(session, trade, 1020, "manual")
            await session.commit()
            assert trade.status == "closed"
            assert trade.pnl is not None and trade.pnl > 0  # +20/share minus costs

    async def test_tc067_live_approve_pending_and_kill(self, client, monkeypatch):
        await _complete_setup(client)
        await _force_market_open(monkeypatch)
        r = await client.post("/api/agent/mode", json={"mode": "live", "confirm": "LIVE"})
        assert r.status_code == 200
        async with SessionLocal() as session:
            from app.models import User
            from app.services.agent import tools as T
            from sqlalchemy import select

            user = (await session.execute(select(User))).scalars().first()
            result = await T.execute_tool(session, user, "propose_trade", {
                "symbol": "NSE:RELIANCE-EQ", "side": "BUY", "instrument": "equity_intraday",
                "entry": 1000, "stop": 990, "target": 1020,
            })
            assert result["status"] == "pending_broker_approval", result
        trades = (await client.get("/api/agent/trades")).json()
        assert trades[0]["mode"] == "live" and trades[0]["status"] == "pending_approval"
        # kill switch halts and forces paper
        r = await client.post("/api/agent/kill")
        assert r.status_code == 200
        body = (await client.get("/api/agent/rules")).json()
        assert body["kill_switch"] is True and body["mode"] == "paper"
        trades = (await client.get("/api/agent/trades")).json()
        assert trades[0]["status"] == "rejected"


class TestMemoryAndChat:
    async def test_tc068_write_note_graph_edges(self, client):
        await _complete_setup(client)
        r = await client.post("/api/agent/memory/notes", json={
            "title": "IT strength", "body": "INFY results beat", "entities": ["INFY", "TCS"],
        })
        assert r.status_code == 200
        g = (await client.get("/api/agent/memory/graph")).json()
        node_ids = {n["id"] for n in g["nodes"]}
        assert "INFY" in node_ids and "TCS" in node_ids
        assert any(e["rel"] == "mentions" and e["to"] == "entity:INFY" for e in g["edges"])

    async def test_tc069_chat_requires_llm_then_streams(self, client, monkeypatch):
        await _complete_setup(client)
        r = await client.post("/api/agent/chat", json={"content": "hello"})
        assert r.status_code == 400  # no LLM connection yet
        await _make_llm(client)

        import app.services.agent.chat as chat_mod

        async def fake_stream(provider, api_key, model, base_url, messages, tools=None):
            yield {"type": "text", "text": "Namaste. Mode is PAPER."}
            yield {"type": "done", "usage": None}

        monkeypatch.setattr(chat_mod.llm_runtime, "stream_chat", fake_stream)
        resp = await client.post("/api/agent/chat", json={"content": "what is my mode?"})
        assert resp.status_code == 200
        body = resp.text
        assert "conversation_id" in body
        assert "Namaste" in body
        convs = (await client.get("/api/agent/conversations")).json()
        assert convs and convs[0]["title"].startswith("what is my mode")
        msgs = (await client.get(f"/api/agent/conversations/{convs[0]['id']}/messages")).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]

    async def test_tc070_jobs_crud_and_status(self, client):
        await _complete_setup(client)
        r = await client.post("/api/agent/jobs", json={
            "name": "scan", "tool_name": "get_system_status", "args": {}, "interval_minutes": 15,
        })
        assert r.status_code == 200
        jobs = (await client.get("/api/agent/jobs")).json()
        assert jobs[0]["name"] == "scan"
        r = await client.post("/api/agent/jobs", json={
            "name": "bad", "tool_name": "propose_trade", "args": {}, "interval_minutes": 15,
        })
        assert r.status_code == 422  # dangerous tools not allowed in jobs
        s = (await client.get("/api/agent/status")).json()
        assert s["mode"] == "paper" and s["kill_switch"] is False
        assert (await client.delete(f"/api/agent/jobs/{jobs[0]['id']}")).status_code == 200


class TestModelSelection:
    async def test_tc074_settings_model_override_used_by_chat(self, client, monkeypatch):
        await _complete_setup(client)
        await _make_llm(client)
        r = await client.patch("/api/agent/settings", json={"model": "llama-3.1-8b-instant"})
        assert r.status_code == 200
        s = (await client.get("/api/agent/settings")).json()
        assert s["model"] == "llama-3.1-8b-instant"

        import app.services.agent.chat as chat_mod

        seen = {}

        async def fake_stream(provider, api_key, model, base_url, messages, tools=None):
            seen["model"] = model
            yield {"type": "text", "text": "ok"}
            yield {"type": "done", "usage": None}

        monkeypatch.setattr(chat_mod.llm_runtime, "stream_chat", fake_stream)
        resp = await client.post("/api/agent/chat", json={"content": "hi"})
        assert resp.status_code == 200
        assert "llama-3.1-8b-instant" in resp.text  # meta event carries selected model
        assert seen["model"] == "llama-3.1-8b-instant"
