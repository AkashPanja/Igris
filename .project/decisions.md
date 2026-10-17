# Decisions

- 2026-10-17: Git repo on branch `main`. Remote origin = https://github.com/AkashPanja/Igris.git
- 2026-10-17: Sprint S1 approved. Port 8080 → 4024.
- 2026-10-17: Font = "Sora" (headings/UI) + "Inter" (body). fontsource.
- 2026-10-17: Motion = framer-motion. Minimal, subtle.
- 2026-10-17: Gradients = emerald → teal → cyan. Dark-mode aware.
- 2026-10-17: No social/Google login. Email + password only.
- 2026-10-17: Sprint 1 ships Overview shell only (no extra dashboard tabs).
- 2026-10-17: Project relocated to /workspace/Igris (persistent mount) after /root/.local reset.
- 2026-10-17 S2: Groww TOTP — user stores base32 secret (encrypted), server generates codes autonomously.
- 2026-10-17 S2: Reauth schedule default 07:30 server-local, per-connection editable on card (applies to both Fyers expiry check + Groww reauth).
- 2026-10-17 S2: PUBLIC_BASE_URL optional, default http://igris.bnfkquodqjp.uk/ (also passed via compose). If unset/localhost → manual flow: user opens Fyers auth URL, pastes auth code back.
- 2026-10-17 S2: Unlimited connections, including multiple of same provider (N Fyers, N Groww).

## 2026-10-17 — S2 implemented (REQ-002)
- Connection model: single encrypted `credentials` JSON (app_secret/totp_secret/access_token) + plain app_id; status ∈ never_authed|connected|needs_auth|error.
- fyers-apiv3 installed with `--no-deps` (pins conflict with growwapi aiohttp>=3.11); needs requests + aws_lambda_powertools; growwapi installed normally + pyotp for TOTP.
- Scheduler: asyncio task (main lifespan), 60s tick; per-connection reauth_time (default 07:30) — Groww auto TOTP login, Fyers expiry→needs_auth + email; email skipped if SMTP unset.
- Tests: fixtures moved to tests/conftest.py; 30/30 pass; frontend build clean.
