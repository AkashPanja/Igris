# Igris — Project Index

**Goal:** Trading web app: broker + LLM connections, Igris agent (chat/tools/memory), paper-first trading.

**Sprint:** S5 — agent team (phase 1 done: roster + Scout + Reporter)
**Story:** S1 foundation, S2 Fyers/Groww, S3 LLM tab, S4 agent/chat/paper-trading, S5 phase 1 background workers

**Blockers:** none. Both broker tokens re-issued/expired — Groww auto-recovers (TOTP), Fyers needs OAuth click (Connections page).

**Live:** :4024 (DATA_DIR=/data), server restart after every backend change.
**Tests:** backend 67 (60 + TC-075..081), frontend `npm run build` clean.
**Push:** GitHub as AkashPanja; commit style: `feat(Sn): …` / `fix(Sn): …`.

**Last completed:** S5 phase 1 (REQ-005): Agents roster page (all9 paper §4.1 agents w/ status/schedule/usage), Scout worker (watchlist % moves → signals w/ dedup + NSE index snapshot), Reporter worker (EOD daily+rolling lessons, memory expiry sweep), agent_runs + usage_log tables, token/cost logging from chat, worker toggles. Fixed: scheduler naive-datetime crash (halted monitor+jobs — critical), GrowwAPI ctor bug (broker fallback never worked).

**Next action:** S5 phase 2 — News & Sentiment worker (free Indian RSS + LLM clustering), Global Macro worker (NSE marketStatus GIFT Nifty + free macro endpoints), Analyst scheduled proposal drafts; then forward-test harness (paper §11).

**Reference material (not requirements):** `.project/research/2026-10-18-multiiagent-trading-paper.md` — user's design paper: multi-agent autonomous trading system (Scout/News/Macro/Analyst → code Risk/Executor/Monitor, shared DB memory, chat-governed rules, paper-first go-live gates). Now driving S5 (user asked "what needs to be done per the research paper").
