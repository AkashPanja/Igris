# Igris — Project Index

**Goal:** Trading web app: broker + LLM connections, Igris agent (chat/tools/memory), paper-first trading.

**Sprint:** S4 — Igris Agent (done, commit c2c2880)
**Story:** S1 foundation, S2 Fyers/Groww, S3 LLM tab, S4 agent/chat/paper-trading complete

**Blockers:** none

**Live:** :4024 (DATA_DIR=/data), server restart after every backend change.
**Tests:** backend 60 tests (49 prior + TC-060..070), frontend `npm run build` clean.
**Push:** GitHub as AkashPanja; commit style: `feat(Sn): …` / `fix(Sn): …`.

**Last completed:** S4 (REQ-004): Igris agent tab — streaming chat w/ tool-calling (groq/openai/anthropic/gemini/cloudflare), shared memory + linked-notes graph, rules w/ hard caps in code, paper engine (costs/slippage/monitor/EOD), live toggle (type LIVE, approve-each), kill switch, notify-on-long, cron jobs, audit log.

**Next action:** user review of /igris → add Groq key on LLM tab and try chat; then decide: Scout/News research workers (paper phase E), force-graph viz, or forward-test harness.

**Reference material (not requirements):** `.project/research/2026-10-18-multiiagent-trading-paper.md` — user's design paper: multi-agent autonomous trading system (Scout/News/Macro/Analyst → code Risk/Executor/Monitor, shared DB memory, chat-governed rules, paper-first go-live gates). Parked until user says how to relate it to Igris.
