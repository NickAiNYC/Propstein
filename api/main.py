"""
Deployment surface: FastAPI on Railway.

NOT Vercel. Vercel's serverless functions have a hard execution ceiling and a
cold-start penalty that a statsmodels GLM fit will blow through, and the
filesystem is ephemeral so your CLV log evaporates. Railway (or Fly, or a
small VPS) gives you a persistent process, a real disk, and a cron. Use
Vercel for the marketing page if you want one.

The weekly job runs on a schedule or via the UI runner, writes files to disk,
and the API serves them. Model fitting NEVER happens inside a request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(BASE_DIR, "src")
VIEWER_DIR = os.path.join(BASE_DIR, "viewer")

sys.path.insert(0, BASE_DIR)
sys.path.insert(0, SRC_DIR)

from agent import clv_report, record_closing  # noqa: E402


def resolve_file(path_env: str, default_filename: str) -> str:
    env_val = os.environ.get(path_env)
    if env_val:
        return env_val
    for cand in [
        os.path.join("/data", default_filename),
        os.path.join(BASE_DIR, default_filename),
        os.path.join(VIEWER_DIR, default_filename),
    ]:
        if os.path.exists(cand):
            return cand
    if os.path.exists("/data"):
        return os.path.join("/data", default_filename)
    return os.path.join(BASE_DIR, default_filename)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    """Refuse to serve until extension signing and session-store policy pass."""
    from api.extension_router import enforce_runtime_security

    enforce_runtime_security()
    yield


app = FastAPI(title="NFL Receiving Props Agent", version="0.2.0", lifespan=_app_lifespan)

# ---------------------------------------------------------------------------
# Foundation freeze (Phase 1): structured JSON logging + request IDs.
# Every log line is one JSON object; every request is correlated by
# X-Request-ID (honor-or-generate, echoed on the response). Additive only —
# no route, payload, or behavior change. See src/observability/logging.py.
# ---------------------------------------------------------------------------
from src.observability.logging import (  # noqa: E402
    RequestContextMiddleware,
    configure_logging,
)

configure_logging()
app.add_middleware(RequestContextMiddleware)

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://propstein.com,http://127.0.0.1:4180,http://localhost:4180",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Admin-Key", "X-Admin-Token", "X-PropStein-API-Key", "X-PropWire-API-Key"],
)

# ---------------------------------------------------------------------------
# PropStein Live Sniper — extension API (additive; see docs/LIVE_SNIPER_AUDIT.md
# S-1/S-3/S-6 mitigations). Two-line include keeps the change reversible.
# ---------------------------------------------------------------------------
from api.extension_router import router as extension_api_router  # noqa: E402
from api.ledger_router import router as ledger_api_router  # noqa: E402

app.include_router(extension_api_router)
app.include_router(ledger_api_router)


# ---------------------------------------------------------------------------
# Entitlement. Whop is the storefront; Stripe is the processor behind it.
# Verify server-side on every request - a client-side check is not a paywall.
# ---------------------------------------------------------------------------

def verify_entitlement(authorization: str | None) -> dict:
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        if token.count(".") == 2:
            try:
                from api.extension_router import verify_session_token
                payload = verify_session_token(token)
                return {
                    "status": "active",
                    "subject": payload.get("sub"),
                    "plan": payload.get("plan"),
                    "jti": payload.get("jti"),
                    "token_type": "pste-ext-v1",
                }
            except HTTPException:
                pass

    key = os.environ.get("WHOP_API_KEY")
    if not key:
        is_production = os.environ.get("APP_ENV", "production").lower() == "production"
        explicit_dev_bypass = os.environ.get("PROPWIRE_ALLOW_DEV_AUTH_BYPASS") == "1"
        if not is_production and explicit_dev_bypass:
            return {"status": "active", "note": "explicit local-development bypass"}
        raise HTTPException(503, "entitlement verification is unavailable")

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]

    import requests
    r = requests.get(
        "https://api.whop.com/api/v2/memberships",
        headers={"Authorization": f"Bearer {key}"},
        params={"membership_id": token}, timeout=10)
    if r.status_code != 200:
        raise HTTPException(401, "could not verify membership")
    m = r.json()
    if m.get("status") not in ("active", "trialing", "completed"):
        raise HTTPException(403, "membership not active")
    return m


@app.get("/health/live")
@app.get("/api/health")
def health_live():
    return {"ok": True, "service": "propwire-web", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/health")
@app.get("/health/ready")
def health_ready():
    checks = {
        "entitlement_configured": bool(os.environ.get("WHOP_API_KEY")),
        "viewer_available": os.path.isfile(os.path.join(VIEWER_DIR, "index.html")),
        "slate_available": any(
            os.path.isfile(os.path.join(VIEWER_DIR, filename))
            for filename in ("slate_2026_w7.json", "slate_projections.json")
        ),
    }
    ok = all(checks.values())
    return JSONResponse(
        {"ok": ok, "checks": checks, "ts": datetime.now(timezone.utc).isoformat()},
        status_code=200 if ok else 503,
    )


# ---------------------------------------------------------------------------
# Core Data Endpoints (Serve pre-computed files; NO model re-fitting)
# ---------------------------------------------------------------------------

@app.get("/api/games")
def get_games(slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7 or 2026_w1)")):
    """Returns the matchup schedule for the requested slate."""
    filename = f"games_{slate}.json"
    p = os.path.join(VIEWER_DIR, filename)
    if not os.path.exists(p):
        p = resolve_file("GAMES_PATH", filename)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return JSONResponse([])


@app.get("/api/slate")
def get_slate(slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7 or 2026_w1)")):
    """Returns weekly slate projections generated by week1.py."""
    specific_file = f"slate_{slate}.json"
    candidates = [
        os.path.join(VIEWER_DIR, specific_file),
        resolve_file("SLATE_PATH", specific_file),
        os.path.join(VIEWER_DIR, "slate_projections.json"),
        resolve_file("SLATE_PATH", "slate_projections.json")
    ]
    for c in candidates:
        if os.path.exists(c):
            with open(c, "r", encoding="utf-8") as f:
                return json.load(f)
    return JSONResponse([])


@app.get("/api/picks")
def get_api_picks(slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7 or 2026_w1)")):
    """Unauthenticated picks endpoint for the local/web interface."""
    specific_file = f"current_picks_{slate.split('_')[-1]}.json"
    candidates = [
        os.path.join(VIEWER_DIR, specific_file),
        os.path.join(VIEWER_DIR, "current_picks.json"),
        resolve_file("PICKS_PATH", "current_picks.json")
    ]
    picks_path = None
    for c in candidates:
        if os.path.exists(c):
            picks_path = c
            break

    if not picks_path:
        return JSONResponse({"picks": [], "note": "no slate generated yet"})

    with open(picks_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    log_path = resolve_file("PICKS_LOG", "picks_log.jsonl")
    data["performance"] = clv_report(log_path) if os.path.exists(log_path) else \
        {"status": "insufficient history"}
    data["disclaimer"] = (
        "Statistical estimates for entertainment and research. Not financial "
        "advice. No outcome is guaranteed. Past performance does not predict "
        "future results. 21+ where legal. If gambling is causing harm, call "
        "1-800-GAMBLER."
    )
    return data


@app.get("/picks")
def picks(authorization: str | None = Header(default=None)):
    """Paywalled customer picks endpoint for storefront integration."""
    verify_entitlement(authorization)
    return get_api_picks()


@app.get("/performance")
@app.get("/api/performance")
def performance():
    """Public and unauthenticated track record."""
    log_path = resolve_file("PICKS_LOG", "picks_log.jsonl")
    return clv_report(log_path) if os.path.exists(log_path) else \
        {"status": "insufficient history"}


# ---------------------------------------------------------------------------
# CLV Tracking & Logging
# ---------------------------------------------------------------------------

@app.get("/api/clv/log")
def get_clv_log():
    """Returns all logged picks and their closing line audit entries."""
    log_path = resolve_file("PICKS_LOG", "picks_log.jsonl")
    if not os.path.exists(log_path):
        return {"rows": [], "report": {"status": "no closing lines recorded yet"}}
    
    rows = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return {
        "rows": rows,
        "report": clv_report(log_path),
    }


@app.post("/api/clv/log")
async def append_clv_log(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_propstein_key: Optional[str] = Header(None, alias="X-PropStein-API-Key"),
    x_propscale_key: Optional[str] = Header(None, alias="X-PropScale-API-Key"),
    x_propwire_key: Optional[str] = Header(None, alias="X-PropWire-API-Key"),
):
    """
    Append a pick to the user-scoped CLV audit log.
    Requires user token; anonymous append is rejected with 401.
    Writes strictly to picks_log_{user_id}.jsonl.
    """
    bearer = (authorization or "").replace("Bearer ", "").strip()
    auth_token = (x_propstein_key or x_propscale_key or x_propwire_key or bearer).strip()
    if not auth_token:
        raise HTTPException(401, "Authentication required to append to CLV audit log")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Scope user_id safely (prevent path traversal)
    raw_user_id = str(body.get("user_id") or "").strip()
    if not raw_user_id:
        raw_user_id = auth_token if len(auth_token) < 48 else hashlib.sha256(auth_token.encode()).hexdigest()[:16]
    safe_user_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw_user_id)
    if not safe_user_id:
        safe_user_id = "user_default"

    base_log_dir = os.path.dirname(resolve_file("PICKS_LOG", "picks_log.jsonl")) or "."
    user_log_path = os.path.join(base_log_dir, f"picks_log_{safe_user_id}.jsonl")
    
    entry = {
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "user_id": safe_user_id,
        "player": body.get("player"),
        "market": body.get("market"),
        "side": body.get("side", "over"),
        "line": float(body.get("line", 0.0)),
        "book": body.get("book", "Consensus"),
        "odds": float(body.get("odds", -110)),
        "model_prob": float(body.get("model_prob", 0.5)),
        "market_prob": float(body.get("market_prob", 0.5)),
        "edge": float(body.get("edge", 0.0)),
        "ev_per_unit": float(body.get("ev_per_unit", 0.0)),
        "kelly_stake": float(body.get("kelly_stake", 0.005)),
        "projection": float(body.get("projection", 0.0)),
        "reasoning": body.get("reasoning", ""),
    }
    if "closing_prob" in body and body["closing_prob"] is not None:
        c_prob = float(body["closing_prob"])
        entry["closing_prob"] = c_prob
        entry_mkt = entry.get("market_prob", 0.5)
        entry["clv"] = (c_prob - entry_mkt) if entry["side"] == "over" \
            else (entry_mkt - c_prob)
    
    with open(user_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    try:
        from src.agents.persistence import TruthStore
        TruthStore().record_clv_entry(entry)
    except Exception:
        pass
        
    return {"status": "ok", "user_id": safe_user_id, "entry": entry, "report": clv_report(user_log_path)}


@app.post("/api/clv/record-closing")
async def post_record_closing(request: Request):
    """Record closing market probability or odds for logged picks."""
    log_path = resolve_file("PICKS_LOG", "picks_log.jsonl")
    if not os.path.exists(log_path):
        raise HTTPException(404, "picks_log.jsonl not found")
        
    body = await request.json()
    # Expects closing dictionary: {(player, market, line): closing_prob}
    # or an array of {player, market, line, closing_prob}
    closing_dict = {}
    if "items" in body and isinstance(body["items"], list):
        for item in body["items"]:
            k = (item["player"], item["market"], float(item["line"]))
            closing_dict[k] = float(item["closing_prob"])
    elif "player" in body:
        k = (body["player"], body["market"], float(body["line"]))
        closing_dict[k] = float(body["closing_prob"])

    record_closing(log_path, closing_dict)
    return {"status": "ok", "report": clv_report(log_path)}


# ---------------------------------------------------------------------------
# Immutable Slate Snapshot Endpoints (Pre-Kickoff & Material Revisions)
# ---------------------------------------------------------------------------

@app.get("/api/snapshots")
def get_snapshots(
    slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7)"),
    game_id: str | None = Query(None, description="Filter by game_id (e.g. 2026_07_NE_CHI)"),
    player_id: str | None = Query(None, description="Filter by player_id"),
    max_created_at: str | None = Query(None, description="Evaluation filter: created_at <= decision_time")
):
    """
    Returns immutable snapshots for a slate.
    Strict evaluation rule: Only returns snapshots whose created_at <= max_created_at if provided.
    """
    filename = f"snapshots_{slate}.json"
    p = os.path.join(VIEWER_DIR, filename)
    if not os.path.exists(p):
        p_jsonl = os.path.join(BASE_DIR, "snapshots", f"snapshots_{slate}.jsonl")
        if os.path.exists(p_jsonl):
            with open(p_jsonl, "r", encoding="utf-8") as f:
                snaps = [json.loads(line) for line in f if line.strip()]
        else:
            return JSONResponse([])
    else:
        with open(p, "r", encoding="utf-8") as f:
            snaps = json.load(f)

    if game_id:
        snaps = [s for s in snaps if s.get("game_id") == game_id]
    if player_id:
        snaps = [s for s in snaps if s.get("player_id") == player_id]
    if max_created_at:
        snaps = [s for s in snaps if s.get("created_at") <= max_created_at]

    return snaps


@app.post("/api/freeze")
async def post_freeze(request: Request):
    """
    Triggers an immutable pre-kickoff or decision-time snapshot.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    season = int(body.get("season", 2026))
    week = int(body.get("week", 7))
    game_id = body.get("game_id")
    snapshot_type = body.get("snapshot_type", "pre_kickoff")

    try:
        from freeze_slate import freeze_slate
        snaps, jsonl_path, viewer_path = freeze_slate(
            season=season,
            week=week,
            game_id=game_id,
            snapshot_type=snapshot_type
        )
        return {
            "status": "ok",
            "count": len(snaps),
            "game_id": game_id or "full_slate",
            "snapshot_type": snapshot_type,
            "jsonl_path": str(jsonl_path),
            "viewer_path": str(viewer_path),
            "sample_content_hash": snaps[0]["content_hash"] if snaps else None
        }
    except Exception as exc:
        raise HTTPException(500, f"Freeze failed: {str(exc)}")


@app.get("/api/injuries")
def get_injuries(
    season: int = Query(2026, description="NFL Season"),
    week: int = Query(7, description="NFL Week")
):
    """
    Returns live injury feed and target redistribution matrices for the slate.
    """
    filename = f"injuries_{season}_w{week}.json"
    p = os.path.join(VIEWER_DIR, filename)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return JSONResponse({"status": "no_injuries_feed", "injuries": [], "impacted_beneficiaries": {}})


@app.get("/api/live-odds")
def get_live_odds():
    """
    Returns live verified odds feed and evaluation against frozen projections.
    """
    p = os.path.join(VIEWER_DIR, "live_odds_feed.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return JSONResponse({"feed_status": "AWAITING_OPENERS", "verified_books_count": 0, "quotes": []})


@app.post("/api/ingest-odds")
async def post_ingest_odds(request: Request):
    """
    Triggers live odds ingestion adapter, evaluates quotes against frozen state,
    and emits immutable first_published / material_revision snapshots.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    season = int(body.get("season", 2026))
    week = int(body.get("week", 7))
    game_id = body.get("game_id")

    try:
        from odds_adapter import OddsIngestionAdapter, EarlyMarketOpenersProvider
        adapter = OddsIngestionAdapter(season=season, week=week, provider=EarlyMarketOpenersProvider())
        summary = adapter.run_ingestion(game_id=game_id)
        return {"status": "ok", "summary": summary}
    except Exception as exc:
        raise HTTPException(500, f"Odds ingestion failed: {str(exc)}")


@app.get("/api/holdout-eval")
def get_holdout_eval(
    season: int = Query(2026, description="NFL Season"),
    week: int = Query(1, description="NFL Week")
):
    """
    Returns chronological holdout evaluation report for a given slate.
    """
    filename = f"holdout_eval_{season}_w{week}.json"
    p = os.path.join(VIEWER_DIR, filename)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    p_eval = os.path.join(BASE_DIR, "evaluation", filename)
    if os.path.exists(p_eval):
        with open(p_eval, "r", encoding="utf-8") as f:
            return json.load(f)
    return JSONResponse({"status": "no_eval"})


# ---------------------------------------------------------------------------
# Weekly Run Action (Shells out to week1.py and streams live progress)
# ---------------------------------------------------------------------------

@app.get("/api/run-week/stream")
async def run_week_stream(
    request: Request,
    season: Any = Query(2026, description="NFL Season"),
    week: Any = Query(1, description="Week Number"),
    odds: bool = Query(False, description="Pull live odds via The Odds API"),
    all_games: bool = Query(True, description="Include all games regardless of kickoff"),
    x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key", description="Admin token HTTP header"),
):
    """
    Executes src/week1.py in a separate process, streaming stdout line-by-line
    via Server-Sent Events (SSE). Strictly gated behind ADMIN_TOKEN in production.
    Validates season and week as strict integers; rejects non-int with 400.
    """
    # Strict integer validation before any subprocess execution
    raw_season = request.query_params.get("season", season)
    raw_week = request.query_params.get("week", week)

    if raw_season is not None:
        if not re.match(r"^\d+$", str(raw_season).strip()):
            raise HTTPException(400, "season must be a strict integer")
    if raw_week is not None:
        if not re.match(r"^\d+$", str(raw_week).strip()):
            raise HTTPException(400, "week must be a strict integer")

    try:
        season_int = int(str(raw_season).strip())
        week_int = int(str(raw_week).strip())
    except (ValueError, TypeError):
        raise HTTPException(400, "season and week must be strict integers")

    if not (2000 <= season_int <= 2050):
        raise HTTPException(400, f"season {season_int} out of valid range (2000-2050)")
    if not (1 <= week_int <= 25):
        raise HTTPException(400, f"week {week_int} out of valid range (1-25)")

    admin_secret = os.environ.get("ADMIN_TOKEN")
    provided_key = x_admin_key
    client_host = request.client.host if request.client else ""
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient")
    if admin_secret:
        if provided_key != admin_secret:
            raise HTTPException(403, "Forbidden: Invalid or missing admin credentials")
    elif not is_localhost:
        raise HTTPException(403, "Forbidden: Pipeline runner requires ADMIN_TOKEN configured for external access")

    cmd = [
        sys.executable,
        os.path.join(SRC_DIR, "week1.py"),
        "--season", str(season_int),
        "--week", str(week_int),
    ]
    if all_games:
        cmd.append("--all-games")
    if odds:
        cmd.append("--odds")

    async def event_generator() -> AsyncGenerator[str, None]:
        yield f"data: [INFO] Starting run for {season} Week {week}...\n\n"
        yield f"data: [INFO] Command: {' '.join(cmd)}\n\n"
        
        proc = subprocess.Popen(
            cmd,
            cwd=BASE_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        try:
            for line in iter(proc.stdout.readline, ""):
                clean_line = line.rstrip("\r\n")
                if clean_line:
                    yield f"data: {clean_line}\n\n"
            proc.stdout.close()
            ret_code = proc.wait()
            
            # Sync files to viewer directory if run produced files in root
            root_slate = os.path.join(BASE_DIR, "slate_projections.json")
            viewer_slate = os.path.join(VIEWER_DIR, "slate_projections.json")
            if os.path.exists(root_slate):
                with open(root_slate, "r") as f_in, open(viewer_slate, "w") as f_out:
                    f_out.write(f_in.read())
                    
            root_picks = os.path.join(BASE_DIR, "current_picks.json")
            viewer_picks = os.path.join(VIEWER_DIR, "current_picks.json")
            if os.path.exists(root_picks):
                with open(root_picks, "r") as f_in, open(viewer_picks, "w") as f_out:
                    f_out.write(f_in.read())

            if ret_code == 0:
                yield "data: [SUCCESS] Slate generation complete! Files refreshed.\n\n"
                yield "event: done\ndata: {\"status\": \"ok\"}\n\n"
            else:
                yield f"data: [ERROR] Process exited with code {ret_code}\n\n"
                yield "event: error\ndata: {\"status\": \"error\", \"code\": " + str(ret_code) + "}\n\n"
        except Exception as exc:
            yield f"data: [FATAL] Subprocess exception: {str(exc)}\n\n"
            yield "event: error\ndata: {\"status\": \"exception\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/webhooks/stripe")
async def legacy_stripe_webhook(request: Request):
    """Legacy Stripe webhook route forwarding to fail-closed webhook handler."""
    return await stripe_webhook(request)


# ---------------------------------------------------------------------------
# B2B Infrastructure API: /api/v1/edges
# High-speed query endpoint querying Postgres or local MarketEdge DB
# ---------------------------------------------------------------------------

@app.get("/api/v1/edges")
def get_v1_edges(
    slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7)"),
    min_edge: float = Query(0.0, description="Minimum edge percentage hurdle"),
    max_edge: float = Query(12.0, description="Maximum edge percentage ceiling (12.0% quarantine limit)"),
    player: str | None = Query(None, description="Optional player name filter"),
    market: str | None = Query(None, description="Optional market filter"),
    limit: int = Query(50, ge=1, le=500, description="Maximum rows returned"),
):
    """
    Direct low-latency B2B executable edge endpoint.
    Enforces a strict 12.0% anomaly ceiling to prevent betting quarantined lines.
    """
    slate_val = getattr(slate, "default", slate) if hasattr(slate, "default") else slate
    min_edge_val = getattr(min_edge, "default", min_edge) if hasattr(min_edge, "default") else min_edge
    max_edge_val = getattr(max_edge, "default", max_edge) if hasattr(max_edge, "default") else max_edge
    limit_val = getattr(limit, "default", limit) if hasattr(limit, "default") else limit
    player_val = getattr(player, "default", player) if hasattr(player, "default") else player
    market_val = getattr(market, "default", market) if hasattr(market, "default") else market

    try:
        min_edge_val = float(min_edge_val)
    except (ValueError, TypeError):
        min_edge_val = 0.0

    try:
        max_edge_val = float(max_edge_val)
    except (ValueError, TypeError):
        max_edge_val = 12.0

    try:
        limit_val = int(limit_val)
    except (ValueError, TypeError):
        limit_val = 50

    db_url = os.getenv("DATABASE_URL")
    records = []

    # 1. Direct Postgres Query via psycopg2 if DATABASE_URL is present
    if db_url:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            query = """
                SELECT "id", "slateId", "playerId", "playerName", "market",
                       "bookLine", "odds", "fairLine", "edgePct", "updatedAt"
                FROM "MarketEdge"
                WHERE "slateId" = %s AND "edgePct" >= %s AND "edgePct" <= %s
            """
            params: list[Any] = [slate_val, min_edge_val, max_edge_val]
            if player_val:
                query += ' AND "playerName" ILIKE %s'
                params.append(f"%{player_val}%")
            if market_val:
                query += ' AND "market" ILIKE %s'
                params.append(f"%{market_val}%")

            query += ' ORDER BY "edgePct" DESC LIMIT %s;'
            params.append(limit_val)

            with psycopg2.connect(db_url) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(query, params)
                    records = [dict(r) for r in cur.fetchall()]
                    for r in records:
                        if "updatedAt" in r and r["updatedAt"]:
                            r["updatedAt"] = r["updatedAt"].isoformat()
            return {
                "status": "success",
                "source": "postgresql",
                "count": len(records),
                "slate": slate_val,
                "data": records
            }
        except Exception as err:
            print(f"[api/v1/edges] Postgres query error: {err}. Trying local SQLite...")

    # 2. Local SQLite fallback (data/market_edges.db)
    sqlite_path = os.path.join(BASE_DIR, "data", "market_edges.db")
    if os.path.exists(sqlite_path):
        try:
            import sqlite3
            conn = sqlite3.connect(sqlite_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            query = """
                SELECT id, slateId, playerId, playerName, market,
                       bookLine, odds, fairLine, edgePct, updatedAt
                FROM MarketEdge
                WHERE slateId = ? AND edgePct >= ? AND edgePct <= ?
            """
            params = [slate_val, min_edge_val, max_edge_val]
            if player_val:
                query += " AND playerName LIKE ?"
                params.append(f"%{player_val}%")
            if market_val:
                query += " AND market LIKE ?"
                params.append(f"%{market_val}%")

            query += " ORDER BY edgePct DESC LIMIT ?"
            params.append(limit_val)

            cur.execute(query, params)
            records = [dict(row) for row in cur.fetchall()]
            conn.close()
            return {
                "status": "success",
                "source": "sqlite",
                "count": len(records),
                "slate": slate_val,
                "data": records
            }
        except Exception as err:
            print(f"[api/v1/edges] SQLite query error: {err}")

    return {
        "status": "success",
        "source": "none",
        "count": 0,
        "slate": slate_val,
        "data": [],
        "note": "MarketEdge database empty or initializing"
    }


# ---------------------------------------------------------------------------
# Diagnostics & Quarantine Endpoint: /api/v1/diagnostics
# Returns quarantined outliers (>12% edge) with strict DO NOT BET directives
# ---------------------------------------------------------------------------

@app.get("/api/v1/diagnostics")
def get_v1_diagnostics(
    slate: str = Query("2026_w7", description="Slate key (e.g. 2026_w7)"),
    limit: int = Query(50, ge=1, le=100, description="Maximum rows returned"),
):
    """
    Returns quarantined anomaly edges (> 12.0% anomaly ceiling)
    along with explicit AGENT_EXECUTION_DIRECTIVE: DO_NOT_BET_QUARANTINED_RECORD.
    """
    slate_val = getattr(slate, "default", slate) if hasattr(slate, "default") else slate
    limit_val = getattr(limit, "default", limit) if hasattr(limit, "default") else limit

    quarantined = []
    db_url = os.getenv("DATABASE_URL")

    if db_url:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            with psycopg2.connect(db_url) as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        'SELECT * FROM "MarketEdge" WHERE "slateId" = %s AND "edgePct" > 12.0 ORDER BY "edgePct" DESC LIMIT %s;',
                        [slate_val, limit_val]
                    )
                    quarantined = [dict(r) for r in cur.fetchall()]
        except Exception:
            pass

    if not quarantined:
        sqlite_path = os.path.join(BASE_DIR, "data", "market_edges.db")
        if os.path.exists(sqlite_path):
            try:
                import sqlite3
                conn = sqlite3.connect(sqlite_path)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM MarketEdge WHERE slateId = ? AND edgePct > 12.0 ORDER BY edgePct DESC LIMIT ?",
                    [slate_val, limit_val]
                )
                quarantined = [dict(r) for r in cur.fetchall()]
                conn.close()
            except Exception:
                pass

    return {
        "status": "success",
        "slate": slate_val,
        "count": len(quarantined),
        "agent_directive": "AGENT_EXECUTION_DIRECTIVE: DO_NOT_BET_QUARANTINED_RECORD. These lines exceed the 12.0% statistical anomaly ceiling and represent unmodeled news, stale projections, or suspended alt-lines. Fade strategies or human inspection required.",
        "quarantined_records": quarantined
    }


# ---------------------------------------------------------------------------
# Cryptographic Receipt Verification: POST /api/v1/verify-receipt
# Resolves 3-stage cryptographic receipt chain (Entry -> Close -> Settlement)
# ---------------------------------------------------------------------------

@app.post("/api/v1/verify-receipt")
async def post_verify_receipt(request: Request):
    """Look up legacy reports and refuse a verdict without the original commitments."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected a JSON object with receipt_hash")

    supplied_hash = body.get("receipt_hash") or body.get("rootHash")
    if not isinstance(supplied_hash, str):
        raise HTTPException(400, "Missing or invalid receipt_hash in request body")
    target_hash = supplied_hash.strip().lower().removeprefix("#")
    if not target_hash:
        raise HTTPException(400, "Missing receipt_hash in request body")

    report_path = Path(resolve_file("AUDIT_REPORT", "public/clv_audit_report.json"))
    if not report_path.exists():
        report_path = Path(resolve_file("AUDIT_REPORT", "viewer/clv_audit_report.json"))
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(503, "Receipt verification data unavailable") from None

    records = report.get("records") if isinstance(report, dict) else None
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise HTTPException(503, "Receipt verification data unavailable")

    commitments = [report.get("ledger_root_hash")]
    for record in records:
        commitments.extend(record.get(field) for field in (
            "entry_receipt", "settlement_receipt", "receipt_hash",
        ))
    if any(isinstance(value, str) and value.strip().lower() == target_hash for value in commitments):
        raise HTTPException(422, "Receipt found, but the report lacks original lifecycle commitments")
    raise HTTPException(404, "Receipt not found")


# ---------------------------------------------------------------------------
# VERIFICATION LAYER (Phase 2): POST /api/v1/verify-quote + context freshness
# Deterministic trust-spine verification for a single quote observation.
# Pure compute over the request body: no demo fallback, no LLM, and no clock
# inside the decision itself (the clock is an explicit input; `now` defaults
# to the server clock only when the caller omits it).
# See src/contracts/verification.py (verification.v1).
# ---------------------------------------------------------------------------

from src.contracts.verification import (  # noqa: E402
    ContextFeedKind,
    ContextFreshnessConfig,
    ReceiptRecord,
    VerificationConfig,
    VERIFICATION_CONTRACTS_VERSION,
    PeerQuote,
    QuoteObservation,
    evaluate_context_freshness,
    verify_quote,
)


class VerifyQuoteRequest(BaseModel):
    """Request body for POST /api/v1/verify-quote. All datetimes must be
    timezone-aware UTC; pydantic rejects naive values with 422 (fail closed on
    ambiguous inputs)."""

    observation: QuoteObservation
    receipts: list[ReceiptRecord] = Field(default_factory=list)
    peers: list[PeerQuote] = Field(default_factory=list)
    now: datetime | None = Field(
        default=None,
        description="Evaluation instant; omit to use the server clock. Pass explicitly for reproducible results.",
    )
    kickoff: datetime | None = Field(
        default=None,
        description="Game kickoff (UTC); drives the time-to-kickoff-aware staleness regime",
    )
    config: VerificationConfig | None = Field(
        default=None,
        description="Optional threshold overrides; defaults mirror the frozen verification.v1 config",
    )


class ContextFreshnessRequest(BaseModel):
    """Request body for POST /api/v1/context-freshness."""

    kind: ContextFeedKind
    last_checked_at: datetime | None = None
    now: datetime | None = None
    config: ContextFreshnessConfig | None = None


@app.post("/api/v1/verify-quote")
async def post_verify_quote(payload: VerifyQuoteRequest):
    """Verify one quote observation against supplied receipts and sharp peers.

    Returns the full VerificationDecision (status, per-clause reasoning with
    actual values and thresholds, conflict snapshot, config echo). This is the
    contract-test surface for the trust spine: callers can reproduce any
    decision byte-for-byte by pinning `now`.
    """
    now_dt = payload.now or datetime.now(timezone.utc)
    try:
        decision = verify_quote(
            observation=payload.observation,
            now=now_dt,
            kickoff=payload.kickoff,
            config=payload.config,
            receipts=payload.receipts,
            peers=payload.peers,
        )
    except ValueError as exc:
        # Fail closed on integrity violations (future-dated observations,
        # naive datetimes): 422, never a silently downgraded status.
        raise HTTPException(422, f"verification rejected the input: {exc}") from exc
    return {
        "contracts_version": VERIFICATION_CONTRACTS_VERSION,
        "generated_at": now_dt.astimezone(timezone.utc).isoformat(),
        "decision": decision.model_dump(mode="json"),
    }


@app.post("/api/v1/context-freshness")
async def post_context_freshness(payload: ContextFreshnessRequest):
    """Evaluate injury/news/lineup feed freshness. Unknown last-check times
    fail closed (is_fresh=False) — unknown does not mean fresh."""
    now_dt = payload.now or datetime.now(timezone.utc)
    try:
        freshness = evaluate_context_freshness(
            kind=payload.kind,
            last_checked_at=payload.last_checked_at,
            now=now_dt,
            config=payload.config,
        )
    except ValueError as exc:
        raise HTTPException(422, f"freshness evaluation rejected the input: {exc}") from exc
    return {
        "contracts_version": VERIFICATION_CONTRACTS_VERSION,
        "generated_at": now_dt.astimezone(timezone.utc).isoformat(),
        "freshness": freshness.model_dump(mode="json"),
    }


# ---------------------------------------------------------------------------
# Settlement Clearinghouse Endpoint: POST /api/v1/settle
# Runs Stage B boxscore consensus grading & finalizes immutable audit receipts
# ---------------------------------------------------------------------------

@app.post("/api/v1/settle")
async def post_settle_slate(
    request: Request,
    slate: str = Query("2026_w7", description="Slate key to settle"),
    admin_token: str | None = Header(None, alias="X-Admin-Token")
):
    """
    Executes official gamebook boxscore resolution.
    Cross-validates Sleeper & Gamebook data, grades active tickets,
    and commits deterministic settlement receipt hashes.
    """
    expected_secret = os.getenv("ADMIN_SETTLEMENT_KEY")
    if not expected_secret:
        raise HTTPException(503, "Settlement is disabled: ADMIN_SETTLEMENT_KEY is not configured")
    if not admin_token or not secrets.compare_digest(admin_token, expected_secret):
        raise HTTPException(403, "Invalid settlement admin token")

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    # Resolve data paths
    bets_path = Path(resolve_file("LOGGED_BETS", f"data/logged_bets_{slate.split('_')[-1]}.json"))
    if not bets_path.exists():
        bets_path = Path(resolve_file("LOGGED_BETS", "data/logged_bets_w7.json"))

    closing_path = Path(resolve_file("SNAPSHOTS_PATH", f"data/snapshots_{slate}.jsonl"))
    if not closing_path.exists():
        closing_path = Path(resolve_file("SNAPSHOTS_PATH", "snapshots/snapshots_2026_w7.jsonl"))

    boxscores_path = Path(resolve_file("BOXSCORES_PATH", f"data/boxscores_{slate}.json"))
    if not boxscores_path.exists():
        boxscores_path = Path(resolve_file("BOXSCORES_PATH", "data/boxscores_2026_w7.json"))

    out_path = Path(resolve_file("AUDIT_REPORT", "public/clv_audit_report.json"))

    from settle_ledger import settle_slate
    try:
        report = settle_slate(
            bets_path=bets_path,
            closing_snapshots_path=closing_path,
            boxscores_path=boxscores_path,
            output_path=out_path,
        )
        return {
            "status": "success",
            "slate": slate,
            "settled_records": report.get("total_records", 0),
            "record": report.get("record_str", "0-0-0"),
            "win_rate_pct": report.get("win_rate_pct", 0.0),
            "beat_close_rate_pct": report.get("beat_close_rate_pct", 0.0),
            "realized_roi_pct": report.get("realized_roi_pct", 0.0),
            "ledger_root_hash": report.get("ledger_root_hash"),
            "generated_at": report.get("generated_at"),
        }
    except Exception as e:
        raise HTTPException(500, f"Settlement engine error: {str(e)}")


# ---------------------------------------------------------------------------
# Live Agentic Sniper Terminal (LangGraph + Redis Streams + Postgres Truth)
# ---------------------------------------------------------------------------

_SNIPER_ENGINE = None


def get_sniper_engine():
    global _SNIPER_ENGINE
    if _SNIPER_ENGINE is None:
        from src.agents.graph import SniperTerminalEngine
        _SNIPER_ENGINE = SniperTerminalEngine()
        _SNIPER_ENGINE.seed_terminal_state()
    return _SNIPER_ENGINE


@app.get("/api/sniper/feed")
def get_sniper_feed(
    sport: str | None = Query(None, description="Optional sport filter: nfl or nba"),
):
    """
    Returns live SniperAlerts, Polymarket CLOB opportunities, Live Board
    remaining-game projections, suppression logs, and CLV ledger summary.
    """
    engine = get_sniper_engine()
    snapshot = engine.get_terminal_snapshot()
    if sport in ("nfl", "nba"):
        snapshot["sniper_alerts"] = [a for a in snapshot["sniper_alerts"] if a.get("sport") == sport]
        snapshot["polymarket_board"] = [p for p in snapshot["polymarket_board"] if p.get("sport") == sport]
        snapshot["live_board"] = [l for l in snapshot["live_board"] if l.get("sport") == sport]
    return snapshot


@app.get("/api/sniper/polymarket")
def get_sniper_polymarket(
    sport: str | None = Query(None, description="Optional sport filter: nfl or nba"),
    top_n: int = Query(5, ge=1, le=20),
):
    """
    Returns top Polymarket CLOB player-prop mispricings ranked by
    `mispricing_bps * liquidity_score`.
    """
    engine = get_sniper_engine()
    items = [opp.model_dump(mode="json") for opp in engine.polymarket_opportunities]
    if sport in ("nfl", "nba"):
        items = [i for i in items if i.get("sport") == sport]
    return {
        "status": "ok",
        "count": len(items[:top_n]),
        "ranking_formula": "mispricing_bps * liquidity_score",
        "opportunities": items[:top_n],
    }


@app.get("/api/sniper/live-board")
def get_sniper_live_board(
    sport: str | None = Query(None, description="Optional sport filter: nfl or nba"),
):
    """
    Returns remaining-game live projections with `minutes_remaining`,
    `usage_surge` badge, and `injury_vacancy` badge.
    """
    engine = get_sniper_engine()
    items = list(engine.live_board_items)
    if sport in ("nfl", "nba"):
        items = [i for i in items if i.get("sport") == sport]
    return {
        "status": "ok",
        "count": len(items),
        "live_board": items,
    }


@app.get("/api/sniper/court-lineups")
def get_sniper_court_lineups():
    """
    Returns live NBA 5-man tactical court lineups + bench rotation + `nba_api`
    Live PlayByPlay substitution ticker.
    """
    engine = get_sniper_engine()
    return {
        "status": "ok",
        "court_lineups": engine.court_lineups,
    }


@app.get("/api/sniper/arb-board")
def get_sniper_arb_board():
    """
    Returns live Cross-Venue Mispricing & Arbitrage Board comparing Bayesian Fair
    Probability against Sportsbook lines (DK/FD) and Polymarket CLOB orderbook.
    """
    engine = get_sniper_engine()
    cards = engine.polymarket_arb_agent.get_arb_board_snapshot()
    return {
        "status": "ok",
        "ws_connected": engine.polymarket_arb_agent.ws_connected,
        "is_stale": not engine.polymarket_arb_agent.ws_connected,
        "count": len(cards),
        "arb_board": cards,
    }


def require_internal_api_key(request: Request) -> None:
    """Protect private ledger and state-changing sniper routes with a configured key."""
    expected = os.environ.get("PROPSTEIN_API_KEY") or os.environ.get("PROPWIRE_API_KEY")
    authorization = request.headers.get("Authorization", "")
    bearer = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    provided = (request.headers.get("X-PropStein-API-Key")
                or request.headers.get("X-PropWire-API-Key") or bearer or "").strip()
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(401, "Unauthorized: configured internal API key required")


@app.post("/api/sniper/polymarket-ws-state")
async def post_sniper_polymarket_ws_state(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Toggles or sets the Polymarket CLOB WebSocket connection state for testing
    the Stale Orderbook Guard (greying out prices and suppressing alerts).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    engine = get_sniper_engine()
    connected = bool(body.get("connected", True))
    reason = str(body.get("reason", "Polymarket CLOB WebSocket disconnected"))
    engine.polymarket_arb_agent.set_ws_connection_state(connected, reason=reason)
    engine.export_static_snapshot()
    return {
        "status": "ok",
        "ws_connected": engine.polymarket_arb_agent.ws_connected,
        "is_stale": not engine.polymarket_arb_agent.ws_connected,
        "arb_board": engine.polymarket_arb_agent.get_arb_board_snapshot(),
    }


@app.get("/api/sniper/webhooks")
def get_sniper_webhooks(user_id: str = Query("default_user"), _: None = Depends(require_internal_api_key)):
    """
    Returns configured Discord and Telegram webhook subscriptions for Alert Routing.
    """
    engine = get_sniper_engine()
    subs = engine.truth.list_webhook_subscriptions(user_id=user_id, active_only=False)
    return {
        "status": "ok",
        "user_id": user_id,
        "subscriptions": subs,
    }


@app.post("/api/sniper/webhooks")
async def post_sniper_webhooks(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Registers or updates Discord and/or Telegram webhook routing subscriptions
    with strict SSRF protection (`discord.com/api/webhooks/...` or Telegram `chat_id`).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    engine = get_sniper_engine()
    dispatcher = engine.polymarket_arb_agent.webhook_dispatcher
    user_id = str(body.get("user_id") or "default_user")
    platform = str(body.get("platform") or "discord").lower()
    webhook_url = str(body.get("webhook_url") or "").strip()
    min_edge_gate = float(body.get("min_edge_gate", 4.0))
    polymarket_only = bool(body.get("polymarket_only", True))
    active_status = bool(body.get("active_status", True))

    try:
        saved = dispatcher.register_subscription(
            user_id=user_id,
            platform=platform,
            webhook_url=webhook_url,
            min_edge_gate=min_edge_gate,
            polymarket_only=polymarket_only,
            active_status=active_status,
        )
        return {"status": "ok", "subscription": saved}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/sniper/webhooks/test")
async def post_sniper_webhooks_test(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Dispatches a formatted dummy Cross-Venue Polymarket Arbitrage alert to verify
    Discord/Telegram connection and returns the formatted payloads.
    """
    from src.services.webhook_dispatcher import (
        format_discord_embed,
        format_telegram_markdown,
        validate_webhook_target,
    )

    try:
        body = await request.json()
    except Exception:
        body = {}

    dummy_alert = {
        "player_id": "nba_giannis",
        "player_name": "Giannis Antetokounmpo",
        "team": "MIL",
        "market": "points",
        "market_label": "PTS Over 31.5",
        "line": 31.5,
        "fair_prob": 0.64,
        "implied_prob": 0.58,
        "poly_ask_price": 0.58,
        "edge_pct": 6.0,
        "depth_tooltip": "$500 available at $0.58, $1,200 at $0.59, $850 at $0.60",
        "deep_link": "https://polymarket.com/event/nba-giannis-antetokounmpo-points-over-31-5",
        "venue_type": "polymarket",
        "book": "Polymarket",
    }

    discord_embed = format_discord_embed(dummy_alert)
    telegram_md = format_telegram_markdown(dummy_alert)

    platform = str(body.get("platform") or "").lower()
    target = str(body.get("webhook_url") or "").strip()
    delivery = None
    if platform and target:
        try:
            validate_webhook_target(platform, target)
            engine = get_sniper_engine()
            sub = engine.polymarket_arb_agent.webhook_dispatcher.register_subscription(
                user_id=str(body.get("user_id") or "default_user"),
                platform=platform,
                webhook_url=target,
                min_edge_gate=float(body.get("min_edge_gate", 4.0)),
                polymarket_only=bool(body.get("polymarket_only", True)),
            )
            delivery = engine.polymarket_arb_agent.webhook_dispatcher._deliver_single_subscription(
                sub,
                dummy_alert,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    return {
        "status": "ok",
        "discord_embed": discord_embed,
        "telegram_markdown": telegram_md,
        "delivery": delivery,
    }


@app.post("/api/sniper/simulate-substitution")
async def post_sniper_simulate_substitution(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Executes a 5-second `nba_api` Live PlayByPlay substitution (`PLAYER1_ID -> PLAYER2_ID`),
    swaps the active player on the tactical court diagram, and immediately triggers
    `bayesian_remaining_game_update` against the decoupled `last_known_odds` cache
    without waiting for the 30-second odds poll.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    engine = get_sniper_engine()
    result = engine.simulate_live_substitution(
        game_id=body.get("game_id", "2026_nba_mil_bos"),
        team=body.get("team", "MIL"),
        sub_out_player_id=body.get("sub_out_player_id"),
        sub_in_player_id=body.get("sub_in_player_id"),
    )
    engine.export_static_snapshot()
    return result


@app.post("/api/sniper/feed-stale")
async def post_sniper_feed_stale(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Endpoint called by `scripts/live_nba_sniper_worker.py` when the live PBP
    feed fails for >= 3 consecutive polls, tripping the Stale Kill Switch and
    greying out the frontend court lineups.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    engine = get_sniper_engine()
    res = engine.mark_court_feed_stale(
        game_id=body.get("game_id", "2026_nba_mil_bos"),
        consecutive_failures=int(body.get("consecutive_failures", 3)),
        reason=body.get("reason", "nba_api Live PBP feed unreachable for 3 consecutive polls"),
    )
    engine.export_static_snapshot()
    return res


@app.post("/api/sniper/simulate-scratch")
async def post_sniper_simulate_scratch(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Triggers an end-to-end simulated late injury scratch through
    InjuryEventAgent -> Redis Stream -> LangGraph StateGraph ->
    ProjectionRecalcAgent -> SniperAgent.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    engine = get_sniper_engine()
    result = engine.simulate_late_scratch(
        scratched_player_name=body.get("scratched_player_name", "Joel Embiid"),
        scratched_player_id=body.get("scratched_player_id", "nba_joel_embiid"),
        team=body.get("team", "PHI"),
        opponent=body.get("opponent", "DET"),
        beneficiary_player_id=body.get("beneficiary_player_id", "nba_tyrese_maxey"),
        beneficiary_player_name=body.get("beneficiary_player_name", "Tyrese Maxey"),
    )
    engine.export_static_snapshot()
    return result


@app.post("/api/sniper/explain")
async def post_sniper_explain(request: Request, _: None = Depends(require_internal_api_key)):
    """
    Read-only post-decision narrator endpoint.
    Returns the locked `reasoning_chain` for an alert or prop without ever
    modifying `fair_prob` or `edge_pct`.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    alert_id = body.get("alert_id")
    prop_id = body.get("prop_id")
    engine = get_sniper_engine()
    alerts = engine.truth.get_recent_alerts(limit=50)
    for al in alerts:
        if (alert_id and al.get("alert_id") == alert_id) or (prop_id and al.get("prop_id") == prop_id):
            return {
                "status": "ok",
                "alert_id": al["alert_id"],
                "prop_id": al["prop_id"],
                "fair_prob_locked": al["fair_prob"],
                "edge_pct_locked": al["edge_pct"],
                "reasoning_chain": al["reasoning_chain"],
                "source_hash": al["source_hash"],
                "model_version": al["model_version"],
            }
    raise HTTPException(404, "Alert not found in truth store")


@app.get("/api/sniper/stream")
async def get_sniper_stream(request: Request):
    """
    Server-Sent Events (SSE) stream pushing real-time SniperAlert events,
    live projection updates, and Stale Kill Switch status to the frontend terminal.
    """
    import asyncio

    engine = get_sniper_engine()

    async def sse_generator() -> AsyncGenerator[str, None]:
        snapshot = engine.get_terminal_snapshot()
        yield f"event: snapshot\ndata: {json.dumps(snapshot, default=str)}\n\n"
        for alert in snapshot.get("sniper_alerts", [])[:5]:
            if await request.is_disconnected():
                break
            yield f"event: sniper_alert\ndata: {json.dumps(alert, default=str)}\n\n"
            await asyncio.sleep(0.15)
        yield f"event: heartbeat\ndata: {json.dumps({'status': 'LIVE_SPINE_HEALTHY', 'ts': datetime.now(timezone.utc).isoformat()})}\n\n"

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/sniper/receipt/{alert_id}")
def get_sniper_receipt(alert_id: str):
    """
    Public (no auth required) endpoint returning a self-contained,
    cryptographically hash-verifiable Sniper Receipt (`SHA-256`) with
    `claim = "No LLM in Decision Path — Verified SHA-256 Receipt"`,
    original `source_hash`, `model_version`, entry vs. closing line/odds,
    and CLV metrics.
    """
    engine = get_sniper_engine()
    receipt = engine.arb_ledger.get_receipt(alert_id)
    if not receipt:
        raise HTTPException(404, f"Receipt '{alert_id}' not found in arb_history")
    return receipt


@app.get("/api/sniper/history")
def get_sniper_history(
    request: Request,
    user_id: Optional[str] = Query(None, description="Optional user ID filter"),
    market: Optional[str] = Query(None, description="Optional market/book filter"),
    prop_type: Optional[str] = Query(None, description="Optional prop_type filter"),
    status: Optional[str] = Query(None, description="Optional status filter (PENDING or GRADED)"),
    clv_positive: bool = Query(False, description="Only return entries with CLV > 0"),
    is_polymarket_arb: Optional[bool] = Query(None, description="Filter by Polymarket arb status"),
    private_only: bool = Query(False, description="Require auth for private user ledger"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    x_propstein_api_key: Optional[str] = Header(None, alias="X-PropStein-API-Key"),
    x_propwire_api_key: Optional[str] = Header(None, alias="X-PropWire-API-Key"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Paginated, filterable Arb History & PnL endpoint.
    Public summary/history is viewable without auth; private user-scoped history
    (`private_only=True` or `user_id` specified) requires a valid API key or Bearer token.
    """
    if private_only or user_id:
        require_internal_api_key(request)

    engine = get_sniper_engine()
    return engine.arb_ledger.get_history(
        user_id=user_id,
        market=market,
        prop_type=prop_type,
        status=status,
        clv_positive=clv_positive,
        is_polymarket_arb=is_polymarket_arb,
        limit=limit,
        offset=offset,
    )


@app.get("/api/ledger")
def get_public_arb_ledger(limit: int = Query(50, ge=1, le=200)):
    """
    Public Arb Engine Performance & Last 50 Graded Receipts endpoint for `/verify`.
    Returns `total_graded_alerts`, `average_clv_beat_pct`, `win_rate_pct`,
    `clv_beat_rate_pct`, `roi_pct`, and the last 50 verifiable SHA-256 receipts.
    """
    engine = get_sniper_engine()
    return engine.arb_ledger.get_public_ledger(limit=limit)


# ---------------------------------------------------------------------------
# Public Verification Landing Page (`/verify/{alert_id}`)
# ---------------------------------------------------------------------------

@app.get("/verify")
@app.get("/verify/{alert_id}")
def get_public_verification_page(alert_id: Optional[str] = None):
    """
    Fully public, zero-auth landing page for shared Sniper Receipts.
    Returns `viewer/verify.html` for both human browser visitors and social scrapers.
    """
    verify_html = os.path.join(VIEWER_DIR, "verify.html")
    if not os.path.exists(verify_html):
        verify_html = os.path.join(VIEWER_DIR, "index.html")
    return FileResponse(verify_html, media_type="text/html")


# ---------------------------------------------------------------------------
# Monetization Engine: Stripe & Whop Subscription Endpoints
# ---------------------------------------------------------------------------

# P2 hardening (v175): billing endpoints require an authenticated principal
# BEFORE any Stripe API call, derive the billing user_id SERVER-SIDE from the
# presented session token (request-body user_id is ignored — a caller cannot
# mint checkout sessions against another user's ledger), clamp redirect URLs
# to the configured app origin, and apply a 3-requests-per-minute
# sliding-window rate limit per principal+IP. The limiter is process-local by
# design: the abuse class it guards against (checkout-session spam that
# exhausts Stripe API quota and trips fraud review) is per-instance.
_BILLING_RATE_WINDOW_S = 60.0
_BILLING_RATE_LIMIT = 3
_billing_rate_buckets: dict[str, list[float]] = {}


def _billing_rate_limited(bucket_key: str) -> bool:
    now = time.monotonic()
    bucket = _billing_rate_buckets.setdefault(bucket_key, [])
    while bucket and now - bucket[0] > _BILLING_RATE_WINDOW_S:
        bucket.pop(0)
    if len(bucket) >= _BILLING_RATE_LIMIT:
        return True
    bucket.append(now)
    # Opportunistic cleanup so a long-lived process cannot grow unbounded.
    if len(_billing_rate_buckets) > 4096:
        stale = [k for k, v in _billing_rate_buckets.items() if not v or now - v[-1] > _BILLING_RATE_WINDOW_S]
        for k in stale:
            _billing_rate_buckets.pop(k, None)
    return False


def _billing_principal(
    request: Request,
    authorization: Optional[str],
    x_propstein_key: Optional[str],
    x_propwire_key: Optional[str],
) -> str:
    """Authenticate a billing caller and derive its server-side user_id.

    Accepts the same session-token surface as /api/clv/log (Authorization:
    Bearer, X-PropStein-API-Key, X-PropWire-API-Key). When a server key is
    configured (PROPSTEIN_API_KEY / PROPWIRE_API_KEY) the presented token
    must match it — 401 otherwise, fail-closed. The principal id is a
    sanitized stable derivation of the token itself, mirroring the
    /api/clv/log scoping rules; body-supplied user_ids are never trusted.
    """
    bearer = (authorization or "").replace("Bearer ", "").strip()
    token = (x_propstein_key or x_propwire_key or bearer).strip()
    if not token:
        raise HTTPException(401, "Authentication required to create a billing session")
    expected = os.environ.get("PROPSTEIN_API_KEY") or os.environ.get("PROPWIRE_API_KEY")
    if expected and token != expected:
        if token.count(".") == 2:
            try:
                from api.extension_router import verify_session_token
                payload = verify_session_token(token)
                safe_sub = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(payload.get("sub", "")))
                return safe_sub or "user_default"
            except HTTPException:
                raise HTTPException(401, "Invalid session token")
        raise HTTPException(401, "Invalid session token")
    if token.count(".") == 2:
        try:
            from api.extension_router import verify_session_token
            payload = verify_session_token(token)
            safe_sub = re.sub(r"[^a-zA-Z0-9_\-]", "_", str(payload.get("sub", "")))
            return safe_sub or "user_default"
        except HTTPException:
            pass
    raw = token if len(token) < 48 else hashlib.sha256(token.encode()).hexdigest()[:16]
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)
    return safe or "user_default"


def _billing_safe_redirect(url: object) -> Optional[str]:
    """Clamp a client-supplied success/cancel/return URL to the app origin.

    Foreign-origin redirect targets are a phishing vector on payment flows:
    Stripe-hosted pages bounce the user to whatever absolute URL was stored
    on the session. Relative paths resolve against APP_URL; anything else
    outside the configured origin is discarded (the caller falls back to the
    BillingService default), never stored and never honored.
    """
    if not isinstance(url, str) or not url.strip():
        return None
    candidate = url.strip()
    base_origin = os.environ.get("APP_URL", "https://propstein.com").rstrip("/")
    if candidate.startswith("/"):
        return base_origin + candidate
    if candidate == base_origin or candidate.startswith(base_origin + "/"):
        return candidate
    return None


@app.post("/api/billing/create-checkout-session")
async def create_checkout_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_propstein_key: Optional[str] = Header(None, alias="X-PropStein-API-Key"),
    x_propwire_key: Optional[str] = Header(None, alias="X-PropWire-API-Key"),
):
    """
    Create a checkout session only when the paid-signup evidence gate is open.

    P2 hardening (v175): authenticated callers only — 401 BEFORE any Stripe
    API call. user_id is derived server-side from the session token (payload
    user_id is ignored), redirect URLs are clamped to the app origin, and the
    endpoint is rate-limited to 3 requests/min per principal+IP.
    """
    principal = _billing_principal(request, authorization, x_propstein_key, x_propwire_key)
    # The public performance record freezes new paid signups while live
    # closing-line alpha remains unproven. Existing customers can still use
    # the billing portal; only new checkout sessions are blocked by default.
    if os.environ.get("PROPSTEIN_PAID_SIGNUPS_ENABLED") != "1":
        raise HTTPException(503, "Paid signups are frozen pending prospective performance evidence")
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    if _billing_rate_limited(f"{principal}:{client_ip}"):
        raise HTTPException(429, "Rate limit exceeded: max 3 checkout sessions per minute")

    from src.services.billing import BillingService

    try:
        body = await request.json()
    except Exception:
        body = {}
    email = body.get("email")
    plan = str(body.get("plan") or "pro_monthly")

    engine = get_sniper_engine()
    billing = BillingService(truth_store=engine.truth)
    return billing.create_checkout_session(
        user_id=principal,
        email=email,
        plan=plan,
        success_url=_billing_safe_redirect(body.get("success_url")),
        cancel_url=_billing_safe_redirect(body.get("cancel_url")),
    )


@app.post("/api/billing/create-portal-session")
async def create_portal_session(
    request: Request,
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_propstein_key: Optional[str] = Header(None, alias="X-PropStein-API-Key"),
    x_propwire_key: Optional[str] = Header(None, alias="X-PropWire-API-Key"),
):
    """
    Create a Stripe Customer Billing Portal session for self-serve management/cancellation.

    P2 hardening (v175): same guard class as checkout — authenticated callers
    only, rate-limited 3/min per principal+IP, return_url clamped to origin.
    """
    principal = _billing_principal(request, authorization, x_propstein_key, x_propwire_key)
    client_ip = (request.client.host if request.client else "unknown") or "unknown"
    if _billing_rate_limited(f"portal:{principal}:{client_ip}"):
        raise HTTPException(429, "Rate limit exceeded: max 3 portal sessions per minute")

    from src.services.billing import BillingService

    body = await request.json()
    customer_id = body.get("customer_id")
    return_url = body.get("return_url")
    if not customer_id:
        raise HTTPException(400, "customer_id is required")

    engine = get_sniper_engine()
    billing = BillingService(truth_store=engine.truth)
    return billing.create_portal_session(customer_id=customer_id, return_url=_billing_safe_redirect(return_url))


@app.post("/api/billing/webhook")
async def stripe_webhook(request: Request):
    """
    Idempotent Stripe webhook receiver verifying HMAC-SHA256 signatures.
    Handles checkout.session.completed, customer.subscription.updated/deleted, invoice.payment_failed.
    """
    from src.services.billing import BillingService, verify_stripe_webhook_signature

    payload_bytes = await request.body()
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not webhook_secret:
        # Fail-closed (Trust Engine invariant): without the configured secret we
        # cannot authenticate the caller. Silently processing unsigned events
        # would let anyone forge checkout.session.completed and unlock PRO.
        print("[billing] STRIPE_WEBHOOK_SECRET not configured — rejecting unsigned webhook", flush=True)
        raise HTTPException(503, "Stripe webhook secret is not configured")

    if not verify_stripe_webhook_signature(payload_bytes, sig_header, webhook_secret):
        # 400 (not 503): a bad signature is a permanent client error — a 503 would
        # make Stripe retry an event that can never authenticate. Fail-closed either way.
        raise HTTPException(400, "Invalid Stripe webhook signature")

    try:
        event = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    engine = get_sniper_engine()
    billing = BillingService(truth_store=engine.truth)
    return billing.process_webhook_event(event)


@app.get("/api/billing/status")
def get_billing_status(
    user_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_propstein_key: Optional[str] = Header(None, alias="X-PropStein-API-Key"),
    x_propwire_key: Optional[str] = Header(None, alias="X-PropWire-API-Key"),
):
    """
    Query active tier status (Free Observer vs. Sniper PRO).
    Integrates Stripe subscription records and Whop entitlement fallback.
    """
    from src.services.billing import BillingService

    engine = get_sniper_engine()
    billing = BillingService(truth_store=engine.truth)
    bearer = (authorization or "").replace("Bearer ", "").strip() or None
    api_key = x_propstein_key or x_propwire_key
    return billing.check_user_entitlement(
        user_id=user_id,
        bearer_token=bearer,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Serve static frontend web application directly from FastAPI on Railway
# ---------------------------------------------------------------------------

if os.path.exists(VIEWER_DIR):
    app.mount("/", StaticFiles(directory=VIEWER_DIR, html=True), name="viewer")
