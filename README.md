# Igris

Self-hosted trading workspace. Sprint 1 delivers the foundation: first-run setup wizard, authentication, secure config, and a deployable shell. Broker integrations (Groww, Fyers) come later.

## Tech stack

| Layer | Choice |
|-------|--------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, SQLite |
| Frontend | React + Vite + TypeScript + Tailwind + framer-motion |
| Auth | Server-side sessions, httpOnly cookie, argon2, CSRF |
| Email | aiosmtplib |
| Deploy | Multi-stage Docker, single container, port **4024** |

## Run locally

### Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data SECRET_KEY=dev-secret uvicorn app.main:app --reload --port 4024
```

### Frontend (dev)

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173, proxies /api to :4024
```

### Tests

```bash
cd backend
DATA_DIR=/tmp/igris-test .venv/bin/python -m pytest tests/ -v
```

## Deploy with Docker (NAS / server)

```bash
cp .env.example .env        # optional: set SECRET_KEY / SETUP_TOKEN
docker compose up -d --build
```

Open `http://<host>:4024` and complete the setup wizard. Data persists in the `igris_data` volume.

## Environment variables

| Var | Required | Description |
|-----|----------|-------------|
| `SECRET_KEY` | No | Fernet key source for SMTP password encryption. Auto-generated to `/data/.secret_key` if unset. |
| `SETUP_TOKEN` | No | If set, wizard step 1 requires this token. |
| `DATA_DIR` | No | Default `/data`. SQLite + secret live here. |
| `PORT` | No | Default `4024`. |

## Project layout

```
backend/          FastAPI app, Alembic, pytest
frontend/         React SPA (Vite)
Dockerfile        Multi-stage build
docker-compose.yml
.project/         File-based engineering memory
```

## Security notes

- Setup routes return **404 permanently** after install (no setup hijack).
- SMTP passwords are encrypted at rest (Fernet, key from `SECRET_KEY`).
- Login locks out after 5 failed attempts (15 min window).
- Password reset links are single-use and expire in 30 minutes.
