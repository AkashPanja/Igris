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

## 2026-10-17 — Groww TOTP Token + QR Code (docs fix)
- Groww docs use "TOTP Token" (Bearer api_key) + "TOTP Secret" (base32, shown as QR). UI/API renamed accordingly.
- CreateConnection now accepts `totp_qr` (otpauth:// payload) as alternative to typed secret; `extract_totp_secret()` parses/validates (base32, len>=16).
- Frontend: "Scan QR image" upload decodes via jsQR client-side and auto-fills the secret; paste of otpauth URL also works.

## 2026-10-17 — Fyers docs compliance
- Per https://fyers.in/api-docs/v3/api/authentication/individual-app/: tokens expire daily 06:30 AM IST — expiry now = next 06:30 IST (was now+24h).
- SDK endpoints (api-t1.fyers.in/api/v3/generate-authcode + /validate-authcode) verified against docs; appIdHash = SHA-256(app_id:app_secret) handled by SessionModel.

## 2026-10-17 — S3: LLM connections
- New table llm_connections (provider, encrypted api_key, base_url, model). Providers: openai, anthropic, gemini, groq, openrouter, custom (OpenAI-compatible base URL).
- Test = real tiny call per provider (chat/messages/generateContent), key masked in UI like broker tokens.
- Tab "LLM" at /llm; model select from static lists + custom id; keys stored for future assistant/insight features.

## 2026-10-18 — S4: Igris agent (paper-inspired, not a merge)
- Chat agent with tools; deterministic Risk Manager/paper engine per research paper §4.2. Hard caps in code (trading.HARD_CAPS), not DB.
- Mode: paper default. Live = website-only, type "LIVE" to enable, autonomy live_approve default (live_auto available). Kill switch closes all + forces paper. Chat cannot change mode/kill (paper §6.3).
- Memory = tables the site renders 1:1 (paper §5); graph v1 = linked notes→entities edges + neighbor list, force-viz later.
- Costs: brokerage ₹20 + STT (2026 rates) + 0.0029% exchange + 18% GST + slippage (5bps equity/10bps F&O). Notify-on-long: side=BUY → in-app + email.
- Tools needing write get 15-min confirm tokens; apply handlers never exposed to the model.
- Scheduler: monitor tick (stop/target/EOD square-off) + user interval jobs (allowed tools whitelist, no propose_trade in jobs).

## 2026-10-18 — S5 phase 1: agent team per research paper §4.1
- Roster shows all nine paper agents; only Main chat is conversational — Scout/Reporter are scheduled code workers (phase 1), News/Macro/Analyst planned as LLM workers (phase 2), Risk/Executor/Monitor always-on code.
- Data sources (user-approved, ₹0): NSE nsepython (allIndices + marketStatus work from this IP; per-stock/quote endpoints 403 blocked → broker APIs are primary for quotes), free Indian RSS for news phase 2, Yahoo-style free macro phase 2. NSE blocked from server IP even with browser impersonation (curl_cffi).
- New tables: agent_runs (worker run history), usage_log (tokens per agent/chat); agent_settings.workers_enabled JSON column (SQLite ALTER migration in init_db).
- Scout: watchlist batch quotes (Fyers → Groww fallback) → ≥3% vs prev close tags a Signal (created_by=scout, expires 15:30 IST, dedup per symbol/day) + NSE index snapshot in run detail.
- Reporter (15:35 IST): daily lesson (metric daily:YYYY-MM-DD, dedup) + rolling30 expectancy row + memory expiry sweep (unpinned notes + expired signals + their edges).
- BUG FIX (critical): scheduler tick crashed on naive SQLite datetimes ("can't compare offset-naive and offset-aware") — monitor + jobs were dead in production; now normalised via as_utc()/tz-aware compare everywhere.
- BUG FIX: trading._broker_client used GrowwAPI(api_key=...) — constructor takes only token; Groww fallback in quotes/live orders never worked. Now uses brokers.groww.client().
- Groww needs_auth now auto-recovers via silent TOTP re-login (once; failure → error + email). Fyers still requires OAuth click.

## 2026-10-19 — S5: broker call validation (official SDK docs + live probes)
- Verified every broker call against official docs/SDK before fixing. Groww SDK: `get_quote(trading_symbol, exchange, segment)` — `segment` is required (our old code omitted it AND called a nonexistent `get_ltp_data`). Groww order response is `payload.groww_order_id` (old code read `order_number`/`order_id` → every live order id would have been lost). Groww F&O product must be `NRML` (`CNC`/`MIS` are cash only); segment `FNO`.
- Fyers symbols: equity `NSE:RELIANCE-EQ`, index `NSE:NIFTY50-INDEX` (not `NSE:NIFTY-INDEX`), options monthly `NSE:NIFTY26OCT24000CE` (yy+3-letter-mon) / weekly `NSE:NIFTY26100824000CE` (yy+m+dd), futures `NSE:NIFTY26OCTFUT`. Groww F&O trading_symbol is monthly-style `NIFTY26OCT24000CE` / `NIFTY26OCTFUT`.
- Option type (CE/PE) is encoded in the strike field (`"24000CE"`) — Trade model has no CE/PE column; avoids a migration. Contract-symbol builders fall back to the plain ticker when expiry/strike are missing (fail-closed).
- Data-source reality (surfaced in chat prompt + Groww test_connection): Groww market-data + option-chain need the separate ₹499/mo Trading API subscription (auth/profile works without it); Fyers needs a valid daily OAuth token (06:30 IST). Indices (NIFTY/BANKNIFTY/VIX/GIFT NIFTY) fall back to the free NSE feed (allIndices `last`; giftnifty is under `marketStatus.giftnifty.LASTPRICE`). SENSEX is BSE-only → not on the free NSE feed.
- New `get_option_chain` tool: Groww `get_option_chain(exchange, underlying, expiry_date)` → Fyers `optionchain({symbol, strikecount, greeks})`; shape-agnostic `_extract_chain_strikes` walks for strike rows (nested CE/PE or flat option_type) and returns a truncated raw payload + honest error chain when neither parses.
- Tests TC-083..086 (formats, get_quote call args + NSE fallback, chain extractor + tool, place_order order-id/product/symbol). 53/53 connections+agent pass; live server restarted :4024.

## 2026-10-19 — S5 follow-up: symbol truth (Fyers symbol master) + Scout quote path
- Fyers `quotes()` hides per-row errors in `d[0].v` (`s:"error"`, `errmsg`) while the envelope says `s:"ok"` — we reported only "empty LTP". Now surfaces the real message + code (-300) and a "did you mean" hint.
- Authoritative symbol source added: `brokers/fyers_symbols.py` downloads/caches the Fyers symbol master daily (`public.fyers.in/sym_details/{NSE_CM,BSE_CM}_sym_master.json`, 10,116+13,169 records, DATA_DIR/fyers_sym). `suggest()` ranks with difflib over same-first-letter tickers (plain substring wrongly matched TNPO→RTNPOWER instead of TNPETRO).
- User's "TNPO" is not an NSE symbol — the real ticker is **TNPETRO** (Tamilnadu Petroproducts). Verified live: TNPETRO ₹124.56, RELIANCE ₹1203.6 via Fyers after the user's OAuth re-auth.
- Index fixes from the master: Bank Nifty's Fyers ticker is `NSE:NIFTYBANK-INDEX` (not BANKNIFTY), Sensex/Bankex are `BSE:*-INDEX`, GIFT NIFTY is absent from Fyers masters → `fyers_spot_symbol` returns "" so callers skip Fyers (free NSE marketStatus path still serves it).
- Fyers weekly-option month codes: Jan–Sep = digits 1–9, **Oct=O, Nov=N, Dec=D** — our builder emitted `261008` instead of `26O08` (wrong in the current month). Fixed + tested.
- BUG FIX (pre-existing, masked by test fakes): `workers.fetch_quotes` never `await`ed `_broker_client` — Scout's real quote path raised `TypeError` on every run since S5 phase 1. Also Fyers prev-close field is `prev_close_price` (we read `ep`/`prev_close` → always None → Scout's ≥3% gate skipped every symbol). NSE index fallback now derives prev from `variation`/`DAYCHANGE`.
- Live verification (Fyers token valid): get_quote → RELIANCE 1203.6, TNPETRO 124.56, NIFTY 22890.75, BANKNIFTY 55522.5 (was broken), SENSEX 73872.38 (was broken, via BSE), GIFT NIFTY 22889.5 (via free NSE). `get_option_chain(NIFTY)` returns 21 strikes w/ LTP+OI via Fyers — no subscription needed for the Fyers chain.
- Tests: TC-083 extended, TC-087 added (suggestion ranking + error surfacing). 6/6 in TestBrokerFormats+scout pass.
