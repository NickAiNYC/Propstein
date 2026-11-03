# PropStein Deployment Guide

## Railway Multi-Service Architecture

PropStein uses a **two-service deployment topology** on Railway backed by the same GitHub repository (`NickAiNYC/PropWire`):

1. **`propstein-web` (FastAPI Web Service)**: Serves `/api/sniper/*`, `/api/v1/edges`, `/api/health`, and the static terminal UI.
2. **`propstein-worker` (Standalone NBA Live PBP Sniper Worker)**: Runs `scripts/live_nba_sniper_worker.py` in a dedicated process so 5-second `nba_api` Live PlayByPlay polling never blocks FastAPI web workers.

```mermaid
flowchart LR
    NBA["nba_api Live PBP (Rotated Proxies)"] -->|5s Poll| Worker["propstein-worker (live_nba_sniper_worker.py)"]
    Worker -->|Railway Private Network POST /api/sniper/simulate-substitution| Web["propstein-web (FastAPI + LangGraph Spine)"]
    Web -->|SSE /api/sniper/stream| UI["PropStein Terminal (propstein.vercel.app)"]
```

---

### 1. Setting Up the Two Services in Railway

1. **Create or Open Your Railway Project**:
   - Service 1 (`propstein-web`): Connected to `NickAiNYC/PropWire` (`main` branch).
   - Click **+ New** $\rightarrow$ **GitHub Repo** $\rightarrow$ select `NickAiNYC/PropWire` again to create Service 2 (`propstein-worker`).

2. **Configure Start Commands**:
   - **`propstein-web` Start Command**:
     ```bash
     uvicorn api.main:app --host 0.0.0.0 --port $PORT
     ```
   - **`propstein-worker` Start Command**:
     ```bash
     python scripts/live_nba_sniper_worker.py
     ```
   - *(Note: If deploying via `Dockerfile` instead of Nixpacks, you can either override the Start Command in the Railway service settings or set `SERVICE_ROLE=worker` on `propstein-worker`.)*

---

### 2. Required Environment Variables (`propstein-worker`)

Set the following variables on the **`propstein-worker`** service in Railway:

| Variable | Example / Value | Purpose |
| :--- | :--- | :--- |
| `PROPWIRE_INTERNAL_API_URL` | `http://propstein-web.railway.internal:8000` | Uses Railway's zero-latency internal private network. **Never** point the worker at the public Vercel URL. |
| `NBA_PROXY_URLS` | `http://user:pass@proxy1:8000,http://user:pass@proxy2:8000` | Comma-separated proxy list rotated on every poll to avoid Akamai WAF IP bans. |
| `SCRAPER_API_KEY` | `your_scraperapi_key` | Optional alternative to `NBA_PROXY_URLS` for automatic proxy wrapping. |
| `NBA_ACTIVE_GAME_IDS` | `2026_nba_mil_bos,2026_nba_gsw_sac` | Active NBA game IDs monitored on a 5-second cadence. |
| `NBA_PBP_POLL_SECONDS` | `5.0` | Play-by-Play polling interval in seconds. |
| `ENVIRONMENT` | `production` | Enforces production logging and fail-closed gates. |
| `LOG_LEVEL` | `INFO` | Emits structured single-line JSON logs for Railway log aggregation. |

---

### 3. Startup Boot-Race Protection & Graceful Shutdown

- **Boot Race Retry (`wait_for_web_service`)**:
  When Railway deploys `propstein-web` and `propstein-worker` simultaneously, `propstein-worker` may boot before `uvicorn` is listening. On startup, the worker pings `${PROPWIRE_INTERNAL_API_URL}/api/health` with exponential backoff (`1s, 2s, 4s, 8s, 16s` — max 5 retries). If `propstein-web` is still unreachable after 5 attempts, the worker logs a `CRITICAL` `boot_race_web_service_unreachable` JSON alert and waits before polling.
- **Graceful Shutdown (`SIGTERM` / `SIGINT`)**:
  During a redeploy, Railway sends `SIGTERM` to the container. `LiveNbaSniperWorker` catches `SIGTERM` and `SIGINT`, finishes the current in-flight poll cycle, closes its health check server and sockets, logs `worker_graceful_shutdown_complete`, and exits with code `0`.
- **Health Check & 60s Heartbeat**:
  When `PORT` or `WORKER_HEALTH_PORT` is set on `propstein-worker`, it exposes `GET /health` (`200 OK`) and emits a structured `worker_heartbeat` log every 60 seconds.
