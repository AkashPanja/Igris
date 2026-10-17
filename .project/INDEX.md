# Igris — Project Index

**Goal:** Trading web app: broker + LLM connections, then consume them (portfolio, insights).

**Sprint:** S3 — LLM Connections (done)
**Story:** S1 foundation, S2 Fyers/Groww, S3 LLM tab complete

**Blockers:** none

**Live:** :4024 (DATA_DIR=/data), server restart after every backend change.
**Tests:** backend 49/49 pass (`pytest tests/`), frontend `npm run build` clean.
**Push:** GitHub as AkashPanja; commit style: `feat(Sn): …` / `fix(Sn): …`.

**Last completed:** S3 (REQ-003): LLM tab — openai/anthropic/gemini/groq/openrouter/custom providers, encrypted keys (masked in UI), model select + custom id, real-call test endpoint. Commit cfe0a76.

**Next action:** pick next milestone with user — candidates: (a) use connections: portfolio/holdings via Fyers+Groww, (b) LLM-powered insights/assistant, (c) live quotes/watchlist.
