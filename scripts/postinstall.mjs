#!/usr/bin/env node
// Propstein 2.0 — Prisma client generation at install time.
//
// One client API, two datasources; the schema is picked by the
// DATABASE_URL protocol so the same postinstall works everywhere:
//
//   postgres:// | postgresql://  -> prisma/schema.postgres.prisma
//                                     (Vercel / Supabase / Neon)
//   file:... | unset             -> prisma/schema.prisma
//                                     (SQLite local preview)
//
// `prisma generate` never touches the database itself, so a missing or
// preview DATABASE_URL at install time is safe — the app only needs the
// real value at runtime (API routes are all force-dynamic).
import { execSync } from "node:child_process";
import { existsSync } from "node:fs";

const url = process.env.DATABASE_URL ?? "";
const isPg = /^postgres(ql)?:\/\//.test(url);
const schema = isPg ? "prisma/schema.postgres.prisma" : "prisma/schema.prisma";

if (!existsSync(schema)) {
  console.error(`[postinstall] schema not found: ${schema}`);
  process.exit(1);
}

console.log(
  `[postinstall] DATABASE_URL ${isPg ? "-> Postgres (production)" : "-> SQLite preview"} — prisma generate --schema ${schema}`,
);
execSync(`npx prisma generate --schema ${schema}`, { stdio: "inherit" });
