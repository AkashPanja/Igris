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


class TestS5Workers:
    """S5: background agent team (paper §4.1) — roster, scout, reporter, expiry."""

    async def test_tc075_roster_returns_full_paper_team(self, client):
        await _complete_setup(client)
        r = await client.get("/api/agent/agents")
        assert r.status_code == 200
        body = r.json()
        names = [a["name"] for a in body["agents"]]
        assert names == ["chat", "scout", "news", "macro", "analyst",
                         "risk", "executor", "monitor", "reporter"]
        planned = {a["name"] for a in body["agents"] if a.get("planned")}
        assert planned == {"news", "macro", "analyst"}
        scout = next(a for a in body["agents"] if a["name"] == "scout")
        assert scout["enabled"] is True and scout["status"] == "never"
        assert "08:30" in scout["schedule"]
        risk = next(a for a in body["agents"] if a["name"] == "risk")
        assert risk["enabled"] is True and risk["kind"] == "code"
        assert body["usage_today"] == {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    async def test_tc076_toggle_worker_persists_and_rejects_code_agents(self, client):
        await _complete_setup(client)
        r = await client.patch("/api/agent/agents/scout", json={"enabled": False})
        assert r.status_code == 200
        scout = next(a for a in (await client.get("/api/agent/agents")).json()["agents"]
                     if a["name"] == "scout")
        assert scout["enabled"] is False
        # code agents are not toggleable
        assert (await client.patch("/api/agent/agents/monitor", json={"enabled": False})).status_code == 422
        assert (await client.patch("/api/agent/agents/nope", json={"enabled": True})).status_code == 422
        # audit trail
        audit = (await client.get("/api/agent/audit")).json()
        assert any(a["action"] == "worker_disabled" and a["detail"] == "scout" for a in audit)

    async def test_tc077_scout_tags_signals_with_dedup(self, client, monkeypatch):
        import app.services.agent.workers as W
        from sqlalchemy import select

        from app.models import Signal, User, WatchlistItem

        async def fake_idx():
            return {"NIFTY 50": (23000.0, 0.5)}, "NIFTY 50 23,000 (+0.50%)"

        monkeypatch.setattr(W, "_nse_index_snapshot", fake_idx)

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            session.add(WatchlistItem(user_id=user.id, symbol="RELIANCE"))
            await session.commit()

            async def fake_quotes(sess, uid, syms):
                return {"RELIANCE": (3000.0, 2800.0)}  # +7.1% ≥ 3% threshold

            rows, detail = await W.run_scout(session, user.id, quotes_fn=fake_quotes)
            await session.commit()
            assert rows == 1
            assert "NIFTY 50" in detail and "RELIANCE" in detail

            rows2, _ = await W.run_scout(session, user.id, quotes_fn=fake_quotes)
            await session.commit()
            assert rows2 == 0  # dedup: one scout signal per symbol per day

            sigs = list((await session.execute(
                select(Signal).where(Signal.user_id == user.id))).scalars())
            assert len(sigs) == 1
            s = sigs[0]
            assert s.created_by == "scout" and s.direction == "long" and s.source == "agent"
            assert s.expires_at is not None and s.score >= 0.5

    async def test_tc078_reporter_daily_and_rolling_lessons(self, client):
        import app.services.agent.workers as W
        from sqlalchemy import select

        from app.models import Lesson, Trade, User, utcnow

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            session.add(Trade(
                id="tc078trade1", user_id=user.id, symbol="RELIANCE", side="BUY",
                instrument="equity_intraday",
                qty=10, entry_px=100.0, exit_px=110.0, pnl=1000.0, status="closed",
                closed_at=utcnow(), mode="paper",
            ))
            await session.commit()

            rows, detail = await W.run_reporter(session, user.id)
            await session.commit()
            assert rows >= 2 and "1 closed" in detail

            lessons = list((await session.execute(
                select(Lesson).where(Lesson.user_id == user.id))).scalars())
            daily = [l for l in lessons if l.metric.startswith("daily:")]
            rolling = [l for l in lessons if l.metric == "rolling30"]
            assert len(daily) == 1 and "1 wins" in daily[0].body and "net ₹1,000" in daily[0].body
            assert len(rolling) == 1 and "expectancy ₹1,000" in rolling[0].body

            # second run: no duplicate daily lesson
            await W.run_reporter(session, user.id)
            await session.commit()
            lessons = list((await session.execute(
                select(Lesson).where(Lesson.user_id == user.id))).scalars())
            assert sum(1 for l in lessons if l.metric.startswith("daily:")) == 1

    async def test_tc079_expiry_removes_stale_keeps_pinned(self, client):
        import app.services.agent.workers as W
        from datetime import timedelta

        from sqlalchemy import select

        from app.models import MemoryEdge, ResearchNote, Signal, User, utcnow

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            past = utcnow() - timedelta(hours=1)
            session.add(ResearchNote(id="note-exp", user_id=user.id, title="intraday",
                                     expires_at=past))
            session.add(ResearchNote(id="note-pin", user_id=user.id, title="keep me",
                                     pinned=True, expires_at=past))
            session.add(ResearchNote(id="note-new", user_id=user.id, title="future",
                                     expires_at=utcnow() + timedelta(hours=2)))
            session.add(ResearchNote(id="forever", user_id=user.id, title="no expiry"))
            session.add(Signal(user_id=user.id, symbol="TCS", created_by="scout",
                               expires_at=past))
            session.add(MemoryEdge(user_id=user.id, from_kind="note", from_id="note-exp",
                                   to_kind="entity", to_id="TCS", rel="mentions"))
            await session.commit()

            rows, detail = await W.run_expiry(session, user.id)
            await session.commit()
            assert rows == 2  # 1 note + 1 signal

            note_ids = set((await session.execute(select(ResearchNote.id))).scalars())
            assert note_ids == {"note-pin", "note-new", "forever"}
            assert (await session.execute(select(Signal))).scalars().all() == []
            edges = list((await session.execute(select(MemoryEdge))).scalars())
            assert edges == []  # orphan edge cleaned

    async def test_tc080_scheduler_tolerates_naive_expires_at(self, client, monkeypatch):
        """Regression: a naive SQLite expires_at crashed the whole scheduler tick."""
        from datetime import datetime, timezone

        import app.services.agent.workers as W
        import app.services.scheduler as sched

        from sqlalchemy import select as sa_select

        from app.models import Connection, User

        async def noop(*a, **k):
            return None

        monkeypatch.setattr(W, "tick", noop)

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(sa_select(User))).scalars().first()
            session.add(Connection(
                id="conn-naive", user_id=user.id, provider="groww", app_id="key",
                credentials="{}", status="connected",
                expires_at=datetime(2026, 1, 1, 12, 0, 0),  # naive + long past
                reauth_time="23:59", last_reauth_at=datetime.now(timezone.utc),
            ))
            await session.commit()

        await sched.tick()  # must not raise

        async with SessionLocal() as session:
            conn = await session.get(Connection, "conn-naive")
            # groww expired token goes straight to silent reauth; without a TOTP
            # secret it fails verification and lands in "error" (no crash, no hang)
            assert conn.status in ("needs_auth", "error")
            assert conn.last_error

    async def test_tc081_chat_logs_token_usage(self, client, monkeypatch):
        await _complete_setup(client)
        await _make_llm(client)

        import app.services.agent.chat as chat_mod

        async def fake_stream(provider, api_key, model, base_url, messages, tools=None):
            yield {"type": "text", "text": "hi"}
            yield {"type": "done", "usage": {"prompt_tokens": 120, "completion_tokens": 30}}

        monkeypatch.setattr(chat_mod.llm_runtime, "stream_chat", fake_stream)
        resp = await client.post("/api/agent/chat", json={"content": "count my tokens"})
        assert resp.status_code == 200

        roster = (await client.get("/api/agent/agents")).json()
        assert roster["usage_today"]["calls"] == 1
        assert roster["usage_today"]["prompt_tokens"] == 120
        assert roster["usage_today"]["completion_tokens"] == 30
        chat_card = next(a for a in roster["agents"] if a["name"] == "chat")
        assert chat_card["status"] == "ok" and chat_card["last_run_at"]


class TestBrokerFormats:
    """S5: every broker call shape validated against official SDK docs."""

    async def test_tc083_symbol_normalization_and_contract_formats(self):
        import app.services.agent.trading as tr

        # spot symbols
        assert tr.fyers_spot_symbol("TNPO") == "NSE:TNPO-EQ"
        assert tr.fyers_spot_symbol("NSE:TNPO-EQ") == "NSE:TNPO-EQ"
        assert tr.fyers_spot_symbol("NIFTY") == "NSE:NIFTY50-INDEX"
        assert tr.fyers_spot_symbol("NIFTY 50") == "NSE:NIFTY50-INDEX"
        # Fyers ticker for Bank Nifty is NIFTYBANK (not BANKNIFTY); Sensex lives on BSE
        assert tr.fyers_spot_symbol("BANKNIFTY") == "NSE:NIFTYBANK-INDEX"
        assert tr.fyers_spot_symbol("SENSEX") == "BSE:SENSEX-INDEX"
        # GIFT NIFTY is absent from the Fyers masters → "" so callers skip Fyers
        assert tr.fyers_spot_symbol("GIFT NIFTY") == ""
        assert tr.is_index_symbol("NIFTY") and not tr.is_index_symbol("TNPO")

        # monthly expiry (2026-10-29 is the last Thursday of Oct 2026)
        assert tr.fyers_contract_symbol("NIFTY", "options", "2026-10-29", "24000CE") == "NSE:NIFTY26OCT24000CE"
        # weekly expiry (2026-10-08, not month end) — Oct uses the letter code "O"
        assert tr.fyers_contract_symbol("NIFTY", "options", "2026-10-08", "24000CE") == "NSE:NIFTY26O0824000CE"
        # weekly in a numeric month (2026-09-25)
        assert tr.fyers_contract_symbol("NIFTY", "options", "2026-09-25", "25000PE") == "NSE:NIFTY2692525000PE"
        assert tr.fyers_contract_symbol("NIFTY", "futures", "2026-10-29") == "NSE:NIFTY26OCTFUT"
        # Groww monthly-style
        assert tr.groww_contract_symbol("NIFTY", "options", "2026-10-29", "24000PE") == "NIFTY26OCT24000PE"
        assert tr.groww_contract_symbol("RELIANCE", "equity_delivery", "") == "RELIANCE"
        # product per Groww docs: F&O → NRML, intraday equity → MIS, else CNC
        assert tr.groww_product("options") == "NRML"
        assert tr.groww_product("futures") == "NRML"
        assert tr.groww_product("equity_intraday") == "MIS"
        assert tr.groww_product("equity_delivery") == "CNC"

    async def test_tc084_get_quote_calls_groww_with_segment_and_nse_fallback(self, client, monkeypatch):
        import app.services.agent.trading as tr
        from sqlalchemy import select

        from app.models import Connection, User

        calls: list[dict] = []

        class FakeGroww:
            def get_quote(self, **kw):
                calls.append(kw)
                return {"payload": {"ltp": 3000.5}}

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            session.add(Connection(
                id="conn-s5-groww", user_id=user.id, provider="groww", app_id="k",
                credentials="{}", status="connected",
            ))
            await session.commit()

            async def fake_broker(sess, uid, provider):
                return (FakeGroww(), None) if provider == "groww" else (None, "no fyers")

            monkeypatch.setattr(tr, "_broker_client", fake_broker)

            px, via = await tr.get_quote(session, user.id, "TNPO")
            assert px == 3000.5 and via == "groww"
            # the exact bug we fixed: get_quote previously called a nonexistent
            # get_ltp_data and omitted segment; now it must pass segment="CASH"
            assert calls and calls[0] == {"trading_symbol": "TNPO", "exchange": "NSE", "segment": "CASH"}

            # index goes to the free NSE fallback (Groww CASH has no indices)
            monkeypatch.setattr(tr, "nse_index_ltp", lambda s: 22900.0 if s == "NIFTY" else None)
            px, via = await tr.get_quote(session, user.id, "NIFTY")
            assert px == 22900.0 and via == "nse"

    async def test_tc085_option_chain_extractor_and_tool(self, client, monkeypatch):
        import app.services.agent.trading as tr
        from app.models import User
        from sqlalchemy import select

        # extractor: Groww-style nested CE/PE
        groww_payload = {"status": "SUCCESS", "payload": {"data": {"oi_data": [
            {"strike_price": 24000, "CE": {"last_price": 120.5, "oi": 1000},
             "PE": {"last_price": 95.2, "oi": 2000}},
        ]}}}
        rows = tr._extract_chain_strikes(groww_payload)
        assert rows and rows[0]["strike"] == 24000
        assert rows[0]["CE"]["ltp"] == 120.5 and rows[0]["PE"]["oi"] == 2000

        # extractor: Fyers-style flat option_type rows
        fyers_payload = {"s": "ok", "data": {"optionsData": {"records": {"optionsData": [
            {"strikePrice": 24100, "optionType": "PE", "lastPrice": 88, "openInterest": 700},
        ]}}}}
        rows = tr._extract_chain_strikes(fyers_payload)
        assert rows and rows[0]["strike"] == 24100 and rows[0]["option_type"] == "PE"

        # get_option_chain via a fake groww client
        class FakeChain:
            def get_option_chain(self, **kw):
                assert kw["exchange"] == "NSE" and kw["underlying"] == "NIFTY"
                return groww_payload

        from app.models import Connection

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            session.add(Connection(
                id="conn-s5-chain", user_id=user.id, provider="groww", app_id="k",
                credentials="{}", status="connected",
            ))
            await session.commit()

            async def fake_broker(sess, uid, provider):
                return (FakeChain(), None) if provider == "groww" else (None, "no fyers")

            monkeypatch.setattr(tr, "_broker_client", fake_broker)
            out = await tr.get_option_chain(session, user.id, "NIFTY")
            assert out["via"] == "groww" and out["strikes"][0]["strike"] == 24000

    async def test_tc086_place_order_uses_groww_order_id_and_nrml(self, client, monkeypatch):
        import app.services.agent.trading as tr
        from app.models import Connection, Rule, Trade, User
        from sqlalchemy import select

        seen: dict = {}

        class FakeGroww:
            def place_order(self, **kw):
                seen.update(kw)
                # docs response: payload.groww_order_id (NOT order_number)
                return {"status": "SUCCESS", "payload": {"groww_order_id": "GMK123", "order_status": "OPEN"}}

        await _complete_setup(client)
        async with SessionLocal() as session:
            user = (await session.execute(select(User))).scalars().first()
            session.add(Connection(
                id="conn-s5-order", user_id=user.id, provider="groww", app_id="k",
                credentials="{}", status="connected",
            ))
            await session.commit()
            rule = await tr.get_rules(session, user.id)

            trade = Trade(
                id="tc086trade", user_id=user.id, symbol="NIFTY", side="BUY",
                instrument="options", expiry="2026-10-29", strike="24000CE",
                qty=50, entry_px=100.0, status="pending_approval", mode="live",
            )

            async def fake_broker(sess, uid, provider):
                return (FakeGroww(), None) if provider == "groww" else (None, "no fyers")

            monkeypatch.setattr(tr, "_broker_client", fake_broker)
            ok, ref = await tr.place_broker_order(session, user.id, trade, rule)
            assert ok and ref == "GMK123"  # read from groww_order_id
            assert seen["segment"] == "FNO"
            assert seen["product"] == "NRML"  # F&O must be NRML, not CNC
            assert seen["trading_symbol"] == "NIFTY26OCT24000CE"  # contract symbol, not bare NIFTY
            assert seen["exchange"] == "NSE" and seen["order_type"] == "MARKET"

    async def test_tc087_symbol_master_suggestions_and_error_surface(self, client, monkeypatch):
        """Canned master: fuzzy ranking must beat naive substring matching.

        Regression: plain substring search matched "TNPO" inside "RTNPOWER"
        instead of the real NSE ticker "TNPETRO"; and get_quote hid the Fyers
        -300 message inside a nested payload (reported only "empty LTP").
        """
        import app.services.agent.trading as tr
        from sqlalchemy import select

        from app.models import User

        canned = {
            "NSE:TNPETRO-EQ": {"symTicker": "NSE:TNPETRO-EQ", "exSymName": "TAMILNADU PETROPRODUCTS L"},
            "NSE:RTNPOWER-EQ": {"symTicker": "NSE:RTNPOWER-EQ", "exSymName": "RATTANPOWER"},
            "NSE:RELIANCE-EQ": {"symTicker": "NSE:RELIANCE-EQ", "exSymName": "RELIANCE INDUSTRIES"},
            "NSE:NIFTY50-INDEX": {"symTicker": "NSE:NIFTY50-INDEX", "exSymName": "NIFTY"},
        }

        import app.services.brokers.fyers_symbols as fs

        monkeypatch.setattr(fs, "load_master", lambda m: canned)

        hits = fs.suggest("TNPO")
        assert "TNPETRO" in hits
        assert "RTNPOWER" not in hits  # same-first-letter prefilter drops it (R ≠ T)
        assert fs.suggest("RELIAN")[:1] == ["RELIANCE"]
        assert fs.suggest("") == []
        assert fs.suggest("ZZQQXX") == []  # nothing similar → no bogus guesses

        class FakeFyers:
            def quotes(self, data):
                return {"s": "ok", "d": [{
                    "n": data["symbols"],
                    "v": {"s": "error", "errmsg": "Please provide a valid symbol", "code": -300},
                    "s": "ok",
                }]}

        async def fake_client(sess, uid, provider):
            return (FakeFyers(), None) if provider == "fyers" else (None, "no groww")

        monkeypatch.setattr(tr, "_broker_client", fake_client)
        monkeypatch.setattr(tr, "nse_index_ltp", lambda s: None)

        await _complete_setup(client)
        async with SessionLocal() as session:
            uid = (await session.execute(select(User))).scalars().first().id
            px, via = await tr.get_quote(session, uid, "TNPO")
        assert px is None
        assert "valid symbol" in via and "TNPETRO" in via  # error surfaced + hint
