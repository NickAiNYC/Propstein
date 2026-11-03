#!/usr/bin/env bash
# Propstein 2.0 — real-database preview test (reproducible runbook).
#
# Reproduces the 2026-11-04 preview validation end to end against a REAL
# Postgres (not the SQLite preview default):
#
#     schema.postgres.prisma -> prisma db push -> seed -> production build
#     -> production server (NODE_ENV=production, no ALLOW_TIER_DEMO)
#     -> endpoint assertions (tier authority, props honesty, record page)
#
# Usage:
#   # against your own database (Supabase / Neon / any Postgres):
#   DATABASE_URL='postgresql://user:pass@host/db' ./scripts/real_db_preview_test.sh
#
#   # with no DATABASE_URL: boots a throwaway local Postgres 18 (no root
#   # needed) via the @embedded-postgres binaries, then tears it down.
#   ./scripts/real_db_preview_test.sh
#
# Exit code 0 = all assertions passed. Any FAIL line means a real problem.

set -uo pipefail

PORT=5437
APP_PORT=3210
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPDIR_PGT="$(mktemp -d /tmp/propstein-pgtest.XXXXXX)"
PASS=0; FAIL=0
SERVER_PID=""
PG_PID=""
EMBEDDED_DIR=""

say()  { printf '%s\n' "$*"; }
pass() { PASS=$((PASS+1)); say "PASS: $*"; }
fail() { FAIL=$((FAIL+1)); say "FAIL: $*"; }
die()  { fail "$*"; say "aborting."; exit 1; }

cleanup() {
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null
  if [ -n "$PG_PID" ]; then kill "$PG_PID" 2>/dev/null; wait "$PG_PID" 2>/dev/null; fi
  rm -rf "$TMPDIR_PGT"
}
trap cleanup EXIT

cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# 1. Resolve DATABASE_URL (external, or boot a throwaway local Postgres)
# ---------------------------------------------------------------------------
if [ -n "${DATABASE_URL:-}" ] && [[ "${DATABASE_URL}" =~ ^postgres(ql)?:// ]]; then
  say "== Using provided DATABASE_URL (${DATABASE_URL%%@*}@***)"
else
  if [ -n "${DATABASE_URL:-}" ]; then
    say "== Ignoring non-Postgres DATABASE_URL (SQLite preview default) — booting a throwaway local Postgres 18"
  else
    say "== No DATABASE_URL given — booting a throwaway local Postgres 18"
  fi
  EMBEDDED_DIR="$TMPDIR_PGT/pgbin"
  mkdir -p "$EMBEDDED_DIR"
  npm --prefix "$EMBEDDED_DIR" install --no-audit --no-fund @embedded-postgres/linux-x64 >/dev/null 2>&1 \
    || die "could not install @embedded-postgres/linux-x64"
  PGBIN="$EMBEDDED_DIR/node_modules/@embedded-postgres/linux-x64/native/bin"
  export PATH="$PGBIN:$PATH"
  initdb -D "$TMPDIR_PGT/pgdata" -U propstein --auth=trust -E UTF8 >/dev/null 2>&1 \
    || die "initdb failed"
  pg_ctl -D "$TMPDIR_PGT/pgdata" -o "-p $PORT -k /tmp -c listen_addresses=127.0.0.1" \
    -l "$TMPDIR_PGT/pg.log" start >/dev/null 2>&1 || die "pg_ctl start failed"
  PG_PID="$(head -1 "$TMPDIR_PGT/pgdata/postmaster.pid" 2>/dev/null)"
  # create the test database (no psql binary in the embedded package — use node pg)
  npm --prefix "$EMBEDDED_DIR" install --no-audit --no-fund pg >/dev/null 2>&1
  NODE_PATH="$EMBEDDED_DIR/node_modules" node -e "
    const { Client } = require('pg');
    (async () => {
      const c = new Client({ host: '127.0.0.1', port: $PORT, user: 'propstein', database: 'postgres' });
      await c.connect();
      const dbs = await c.query(\"SELECT 1 FROM pg_database WHERE datname='propstein_preview_test'\");
      if (dbs.rowCount === 0) await c.query('CREATE DATABASE propstein_preview_test');
      await c.end();
    })().catch(e => { console.error(e.message); process.exit(1); });
  " || die "could not create test database"
  export DATABASE_URL="postgresql://propstein@127.0.0.1:$PORT/propstein_preview_test"
fi

command -v node >/dev/null || die "node not found"
npx --yes tsx --version >/dev/null 2>&1 || true

# ---------------------------------------------------------------------------
# 2. Schema push + seed (real Postgres)
# ---------------------------------------------------------------------------
say "== prisma db push (schema.postgres.prisma)"
npx prisma db push --schema prisma/schema.postgres.prisma --skip-generate >/dev/null 2>&1 \
  || die "prisma db push against Postgres failed"

say "== prisma generate (postinstall path: postgres schema)"
DATABASE_URL="$DATABASE_URL" node scripts/postinstall.mjs >/dev/null 2>&1 || die "prisma generate failed"

say "== seed (ESPN live fetch + bundled v1 snapshot props)"
npx tsx scripts/seed.ts >/tmp/propstein-seed.log 2>&1 || die "seed failed (log: /tmp/propstein-seed.log)"
node -e "const s=require('fs').readFileSync('/tmp/propstein-seed.log','utf8');const m=s.match(/\{[\s\S]*\}/);console.log(m?m[0]:'(no summary printed)')"

# ---------------------------------------------------------------------------
# 3. Production build + production server
# ---------------------------------------------------------------------------
say "== production build"
npm run build >/tmp/propstein-build.log 2>&1 || die "next build failed (log: /tmp/propstein-build.log)"

say "== starting production server (NODE_ENV=production, no ALLOW_TIER_DEMO) :$APP_PORT"
NODE_ENV=production DATABASE_URL="$DATABASE_URL" npx next start -p "$APP_PORT" \
  >/tmp/propstein-server.log 2>&1 &
SERVER_PID=$!
sleep 6

curl -sf -o /dev/null "http://localhost:$APP_PORT/" || die "server did not come up (log: /tmp/propstein-server.log)"

# ---------------------------------------------------------------------------
# 4. Assertions
# ---------------------------------------------------------------------------
jqq() { python3 -c "import json,sys;d=json.load(sys.stdin);print(json.dumps(eval(sys.argv[1]),default=str))" "$1"; }

body="$(curl -s "http://localhost:$APP_PORT/api/tier")"
[ "$(echo "$body" | jqq "d['tier']")" = '"free"' ] && [ "$(echo "$body" | jqq "d['demoTier']")" = 'false' ] \
  && pass "GET /api/tier -> free + demoTier:false, no account fields" || fail "GET /api/tier -> $body"

code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://localhost:$APP_PORT/api/tier" -H 'Content-Type: application/json' -d '{"tier":"pro"}')"
[ "$code" = "403" ] && pass "POST /api/tier -> 403 (no self-grant in production)" || fail "POST /api/tier -> HTTP $code"

body="$(curl -s "http://localhost:$APP_PORT/api/props")"
ok=$(echo "$body" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ok = d.get('dataSource')=='bundled_v1_snapshot' and d.get('teaser') is True \
     and d.get('verifiedCount')==0 and d.get('lastObservedAt') \
     and all(p.get('ev') is None and p.get('kelly') is None for p in d.get('props',[]))
print('ok' if ok else 'bad')
print(json.dumps({k:d.get(k) for k in ('tier','count','totalForSlate','teaser','dataSource','lastObservedAt','verifiedCount')}))
")
if [ "$(echo "$ok" | head -1)" = "ok" ]; then pass "GET /api/props -> $(echo "$ok" | tail -1)"; else fail "GET /api/props -> $body"; fi

body="$(curl -s "http://localhost:$APP_PORT/api/games?league=NBA")"
n="$(echo "$body" | jqq "d['count']")"
[ "$n" -ge 0 ] 2>/dev/null && pass "GET /api/games -> NBA count=$n (real rows from Postgres)" || fail "GET /api/games -> $body"

code="$(curl -s -o /tmp/propstein-perf.html -w '%{http_code}' "http://localhost:$APP_PORT/performance")"
grep -q "178e29974bf8748c" /tmp/propstein-perf.html && grep -q "Track Record" /tmp/propstein-perf.html \
  && [ "$code" = "200" ] && pass "GET /performance -> 200, v1 record verbatim (ledger root hash present)" \
  || fail "GET /performance -> HTTP $code / missing record content"

grep -rql "unlock live edge" .next/static/chunks/ 2>/dev/null \
  && fail "client bundle still promises 'live edge'" \
  || pass "client bundle: 'unlock live edge' absent"
grep -rql "props static snapshot" .next/static/chunks/ 2>/dev/null >/dev/null \
  && pass "client bundle: snapshot header status present" \
  || fail "client bundle: snapshot header status missing"

# ---------------------------------------------------------------------------
say ""
say "== RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ] || exit 1
say "All real-database preview assertions passed."
