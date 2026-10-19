# Igris — Project Index

**Goal:** Trading web app: broker + LLM connections, Igris agent (chat/tools/memory), paper-first trading.

**Sprint:** S5 — agent team (phase 1 done: roster + Scout + Reporter; broker-call validation done)
**Story:** S1 foundation, S2 Fyers/Groww, S3 LLM tab, S4 agent/chat/paper-trading, S5 phase 1 background workers, S5 broker-call validation

**Blockers:** none. Both broker tokens re-issued/expired — Groww auto-recovers (TOTP), Fyers needs OAuth click (Connections page).

**Live:** :4024 (DATA_DIR=/data), server restart after every backend change.
**Tests:** backend 54 in connections+agent files (incl. TC-083..087), frontend `npm run build` clean.
**Push:** GitHub as AkashPanja; commit style: `feat(Sn): …` / `fix(Sn): …`.

**Last completed:** S5 broker-call validation **+ symbol truth**. Fixed: `get_quote` (Fyers symbol normalization, Groww `segment="CASH"`, free-NSE index fallback incl. GIFT NIFTY), `place_broker_order` (`payload.groww_order_id`, F&O `NRML`, contract symbols), new `get_option_chain` tool (live: 21 NIFTY strikes via Fyers). Then per official Fyers symbol master (10,116 instruments): nested `-300` errors now surfaced with "did you mean" hints (`brokers/fyers_symbols.py`, difflib ranking — user's "TNPO" → real ticker **TNPETRO**), Bank Nifty fixed to `NSE:NIFTYBANK-INDEX`, Sensex → `BSE:SENSEX-INDEX`, GIFT NIFTY skips Fyers, weekly option month codes Oct/Nov/Dec = `O`/`N`/`D`. **Pre-existing critical fix:** `fetch_quotes` never awaited `_broker_client` → Scout's quote path crashed every run since S5 phase 1 (masked by test fakes) + Fyers `prev_close_price` was unread (Scout's %-gate skipped all symbols). Live-verified: RELIANCE 1203.6, TNPETRO 124.56, NIFTY/BANKNIFTY/SENSEX/GIFT NIFTY all resolve. Tests TC-083..087.

**Next action:** S5 phase 2 — News & Sentiment worker (free Indian RSS + LLM clustering), Global Macro worker (NSE marketStatus GIFT Nifty + free macro endpoints), Analyst scheduled proposal drafts; then forward-test harness (paper §11).

**Reference material (not requirements):** `.project/research/2026-10-18-multiiagent-trading-paper.md` — user's design paper: multi-agent autonomous trading system (Scout/News/Macro/Analyst → code Risk/Executor/Monitor, shared DB memory, chat-governed rules, paper-first go-live gates). Now driving S5 (user asked "what needs to be done per the research paper").
