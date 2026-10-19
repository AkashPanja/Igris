# Igris — Project Index

**Goal:** Trading web app: broker + LLM connections, Igris agent (chat/tools/memory), paper-first trading.

**Sprint:** S5 — agent team (phase 1 done: roster + Scout + Reporter; broker-call validation done)
**Story:** S1 foundation, S2 Fyers/Groww, S3 LLM tab, S4 agent/chat/paper-trading, S5 phase 1 background workers, S5 broker-call validation

**Blockers:** none. Both broker tokens re-issued/expired — Groww auto-recovers (TOTP), Fyers needs OAuth click (Connections page).

**Live:** :4024 (DATA_DIR=/data), server restart after every backend change.
**Tests:** backend 53 in connections+agent files (incl. TC-083..086), frontend `npm run build` clean.
**Push:** GitHub as AkashPanja; commit style: `feat(Sn): …` / `fix(Sn): …`.

**Last completed:** S5 broker-call validation (per research paper + official SDK docs): `get_quote` rewritten (Fyers `NSE:RELIANCE-EQ`/`NSE:NIFTY50-INDEX` normalization, Groww `get_quote(segment="CASH")` — was calling nonexistent `get_ltp_data`/missing segment, free-NSE index fallback incl. GIFT NIFTY `LASTPRICE`), `place_broker_order` fixed (Groww reads `payload.groww_order_id` — was `order_number` so every order id was lost; F&O product `NRML` not `CNC`; contract symbols `NIFTY26OCT24000CE` monthly / weekly / `...FUT`), new `get_option_chain` tool + shape-agnostic extractor + raw fallback, Groww `test_connection` probes a CASH quote and reports the subscription requirement, chat prompt documents data-source limits. Tests TC-083..086. **53/53 connections+agent pass.**

**Next action:** S5 phase 2 — News & Sentiment worker (free Indian RSS + LLM clustering), Global Macro worker (NSE marketStatus GIFT Nifty + free macro endpoints), Analyst scheduled proposal drafts; then forward-test harness (paper §11).

**Reference material (not requirements):** `.project/research/2026-10-18-multiiagent-trading-paper.md` — user's design paper: multi-agent autonomous trading system (Scout/News/Macro/Analyst → code Risk/Executor/Monitor, shared DB memory, chat-governed rules, paper-first go-live gates). Now driving S5 (user asked "what needs to be done per the research paper").
