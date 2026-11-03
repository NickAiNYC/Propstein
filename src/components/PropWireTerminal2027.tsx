"use client";

import React, { useState } from "react";

interface PlayerRow {
  id: string;
  pos: "WR" | "TE" | "RB";
  initials: string;
  name: string;
  team: string;
  role: string;
  drivers: { label: string; value: string; type: "alpha" | "volume" | "air" | "deep" }[];
  matchup: string;
  env?: "Dome" | "Wind";
  fair: number;
  proj: number;
  ciLow: number;
  ciHigh: number;
}

const SAMPLE_SLATE: PlayerRow[] = [
  {
    id: "puka-nacua",
    pos: "WR",
    initials: "PN",
    name: "Puka Nacua",
    team: "LA",
    role: "Featured WR",
    drivers: [
      { label: "alpha", value: "31%", type: "alpha" },
      { label: "air lead", value: "42%", type: "air" },
    ],
    matchup: "LA vs LAC",
    env: "Dome",
    fair: 118.0,
    proj: 127.0,
    ciLow: 68,
    ciHigh: 188,
  },
  {
    id: "ceedee-lamb",
    pos: "WR",
    initials: "CL",
    name: "CeeDee Lamb",
    team: "DAL",
    role: "Featured WR",
    drivers: [
      { label: "alpha", value: "34%", type: "alpha" },
      { label: "deep", value: "13.8 adot", type: "deep" },
    ],
    matchup: "DAL vs ARI",
    fair: 114.0,
    proj: 123.6,
    ciLow: 66,
    ciHigh: 183,
  },
  {
    id: "jaxon-smith-njigba",
    pos: "WR",
    initials: "JS",
    name: "Jaxon Smith-Njigba",
    team: "SEA",
    role: "Featured WR",
    drivers: [
      { label: "alpha", value: "37%", type: "alpha" },
      { label: "volume", value: "9.4 tgt", type: "volume" },
    ],
    matchup: "SEA vs CHI",
    fair: 113.5,
    proj: 123.0,
    ciLow: 66,
    ciHigh: 182,
  },
  {
    id: "amon-ra-st-brown",
    pos: "WR",
    initials: "AS",
    name: "Amon-Ra St. Brown",
    team: "DET",
    role: "Featured WR",
    drivers: [{ label: "alpha", value: "33%", type: "alpha" }],
    matchup: "DET vs MIN",
    env: "Dome",
    fair: 90.0,
    proj: 98.2,
    ciLow: 52,
    ciHigh: 145,
  },
  {
    id: "zay-flowers",
    pos: "WR",
    initials: "ZF",
    name: "Zay Flowers",
    team: "BAL",
    role: "Featured WR",
    drivers: [{ label: "alpha", value: "32%", type: "alpha" }],
    matchup: "BAL @ BUF",
    fair: 85.0,
    proj: 93.0,
    ciLow: 49,
    ciHigh: 138,
  },
  {
    id: "jamarr-chase",
    pos: "WR",
    initials: "JC",
    name: "Ja'Marr Chase",
    team: "CIN",
    role: "Featured WR",
    drivers: [{ label: "volume", value: "9.7 tgt", type: "volume" }],
    matchup: "CIN vs TEN",
    fair: 72.5,
    proj: 79.7,
    ciLow: 42,
    ciHigh: 118,
  },
];

export default function PropWireTerminal2027() {
  const [sport, setSport] = useState<"NFL" | "NBA">("NFL");
  const [mode, setMode] = useState<"ACTIVE" | "TOP" | "ALL">("TOP");
  const [market, setMarket] = useState<"Yards" | "Rec" | "TD">("Yards");
  const [pos, setPos] = useState<"All" | "WR" | "TE" | "RB">("All");
  const [view, setView] = useState<"Table" | "Grid">("Table");
  const [search, setSearch] = useState("");
  const [simulatingId, setSimulatingId] = useState<string | null>(null);
  const [simLine, setSimLine] = useState<string>("");

  return (
    <div className="min-h-screen bg-[#050811] text-slate-100 selection:bg-sky-500/30 selection:text-sky-200">
      {/* Ambient Top Sapphire Radial Glow */}
      <div className="pointer-events-none fixed inset-x-0 -top-40 z-0 mx-auto h-80 max-w-5xl rounded-full bg-sky-500/[0.07] blur-[120px]" />

      {/* 1. TOP APP BAR */}
      <header className="relative z-30 border-b border-white/[0.06] bg-[#050811]/80 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-6 py-3">
          <div className="flex items-center gap-4">
            <span className="font-mono text-lg font-extrabold tracking-wider text-white italic">
              PROP<span className="text-sky-400">STEIN</span>
            </span>
            <div className="flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-500/[0.06] px-3 py-1 text-[11px] font-mono text-sky-300">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-400 shadow-[0_0_8px_#38bdf8]" />
              UNVERIFIED · 25s
            </div>
          </div>
          <div className="flex items-center gap-2.5 text-xs font-medium">
            <button className="rounded-full border border-white/10 bg-white/[0.04] px-3.5 py-1.5 text-slate-200 transition hover:border-sky-400/30 hover:bg-sky-500/10">
              W8 Unverified
            </button>
            <button className="flex items-center gap-1.5 rounded-full border border-sky-400/25 bg-sky-500/10 px-3.5 py-1.5 text-sky-300 shadow-[0_0_15px_rgba(56,189,248,0.12)] transition hover:bg-sky-500/20">
              <span className="h-1.5 w-1.5 rounded-full bg-sky-400" />7 Alerts
            </button>
            <button className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-slate-300 transition hover:border-white/20 hover:text-white">
              Sniper
            </button>
            <button className="rounded-full border border-white/10 bg-white/[0.03] px-3.5 py-1.5 text-slate-300 transition hover:border-white/20 hover:text-white">
              Ledger
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-[1440px] px-6 pt-4 pb-20">
        {/* 2. FLOATING COMMAND & FILTER DOCK (Zero Label Overlap) */}
        <div className="sticky top-3 z-30 mb-5 flex flex-wrap items-center justify-between gap-2.5 rounded-2xl border border-sky-400/[0.14] bg-[#070C17]/90 p-2 shadow-[0_16px_40px_rgba(2,6,23,0.85)] backdrop-blur-2xl">
          <div className="flex flex-wrap items-center gap-2">
            {/* Sport Pill */}
            <div className="flex items-center rounded-xl border border-white/[0.06] bg-[#04070E] p-1">
              {(["NFL", "NBA"] as const).map((item) => (
                <button
                  key={item}
                  onClick={() => setSport(item)}
                  className={`rounded-lg px-3 py-1 text-xs font-semibold transition ${
                    sport === item
                      ? "border border-sky-400/30 bg-sky-500/15 text-sky-300 shadow-[0_0_12px_rgba(56,189,248,0.2)]"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>

            {/* Search Input */}
            <div className="relative flex items-center">
              <span className="pointer-events-none absolute left-3 text-xs text-slate-500">
                ⌕
              </span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search player or team..."
                className="h-8 w-52 rounded-xl border border-white/[0.06] bg-[#04070E] pr-7 pl-8 text-xs text-slate-200 placeholder-slate-500 transition focus:border-sky-400/40 focus:outline-none"
              />
              <kbd className="pointer-events-none absolute right-2 rounded border border-white/10 bg-white/[0.04] px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                /
              </kbd>
            </div>

            {/* Mode Selector */}
            <div className="flex items-center rounded-xl border border-white/[0.06] bg-[#04070E] p-1 font-mono text-xs">
              <span className="px-2 text-[10px] font-semibold tracking-wider text-slate-500 uppercase">
                Mode
              </span>
              <button
                onClick={() => setMode("ACTIVE")}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition ${
                  mode === "ACTIVE"
                    ? "border border-sky-400/30 bg-sky-500/15 text-sky-300"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                ACTIVE <span className="text-[10px] opacity-70">0</span>
              </button>
              <button
                onClick={() => setMode("TOP")}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition ${
                  mode === "TOP"
                    ? "border border-sky-400/30 bg-sky-500/15 text-sky-300 shadow-[0_0_12px_rgba(56,189,248,0.18)]"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                TOP <span className="text-[10px] text-sky-400">25</span>
              </button>
              <button
                onClick={() => setMode("ALL")}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 transition ${
                  mode === "ALL"
                    ? "border border-sky-400/30 bg-sky-500/15 text-sky-300"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                ALL <span className="text-[10px] opacity-70">422</span>
              </button>
            </div>

            {/* Market Selector */}
            <div className="flex items-center rounded-xl border border-white/[0.06] bg-[#04070E] p-1 text-xs">
              <span className="px-2 font-mono text-[10px] font-semibold tracking-wider text-slate-500 uppercase">
                Market
              </span>
              {(["Yards", "Rec", "TD"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setMarket(m)}
                  className={`rounded-lg px-2.5 py-1 font-medium transition ${
                    market === m
                      ? "border border-sky-400/30 bg-sky-500/15 text-sky-200 shadow-[0_0_10px_rgba(56,189,248,0.15)]"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>

            {/* Position Selector */}
            <div className="flex items-center rounded-xl border border-white/[0.06] bg-[#04070E] p-1 text-xs">
              <span className="px-2 font-mono text-[10px] font-semibold tracking-wider text-slate-500 uppercase">
                Pos
              </span>
              {(["All", "WR", "TE", "RB"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setPos(p)}
                  className={`rounded-lg px-2.5 py-1 font-medium transition ${
                    pos === p
                      ? "border border-sky-400/30 bg-sky-500/15 text-sky-200"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Right View Toggle */}
          <div className="flex items-center gap-2">
            <div className="flex items-center rounded-xl border border-white/[0.06] bg-[#04070E] p-1 text-xs">
              {(["Table", "Grid"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-lg px-3 py-1 font-medium transition ${
                    view === v
                      ? "border border-sky-400/30 bg-sky-500/15 text-sky-200"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {v}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 3. SAPPHIRE 4-COLUMN TELEMETRY RIBBON */}
        <section className="relative mb-6 grid w-full grid-cols-1 gap-px overflow-hidden rounded-2xl border border-sky-400/[0.14] bg-sky-400/[0.08] shadow-[0_24px_60px_rgba(2,6,23,0.9)] lg:grid-cols-4">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-sky-400/40 to-transparent" />

          {/* Col 1: Universe */}
          <div className="relative bg-[#070B14]/95 p-5">
            <span className="text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">
              Universe
            </span>
            <div className="mt-1.5 flex items-baseline gap-2.5 font-mono tabular-nums">
              <span className="text-3xl font-bold tracking-tight text-white">422</span>
              <span className="text-sm text-slate-400">Modeled</span>
              <span className="ml-1 h-2 w-2 rounded-full bg-sky-400 shadow-[0_0_10px_#38bdf8]" />
            </div>
            <div className="mt-0.5 text-xs text-slate-400">
              <strong className="font-mono text-white">0</strong> Audited Live Lines
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-1.5 font-mono text-[10px] text-slate-400">
              <span className="rounded bg-white/[0.03] px-1.5 py-0.5">&lt;5% Sub</span>
              <span className="rounded bg-white/[0.03] px-1.5 py-0.5">5.0% Base</span>
              <span className="rounded border border-sky-400/30 bg-sky-400/10 px-1.5 py-0.5 text-sky-300">
                ● 10.0% Gate
              </span>
              <span className="rounded bg-blue-500/15 px-1.5 py-0.5 text-blue-300">
                15%+ Alpha
              </span>
            </div>
          </div>

          {/* Col 2: Calibration */}
          <div className="relative overflow-hidden bg-[#070B14]/95 p-5">
            <div className="pointer-events-none absolute -bottom-10 left-1/2 h-28 w-48 -translate-x-1/2 rounded-full bg-sky-500/15 blur-2xl" />
            <span className="text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">
              Calibration
            </span>
            <div className="mt-1.5 flex items-baseline gap-2 font-mono tabular-nums">
              <span className="text-3xl font-bold tracking-tight text-white">74.2%</span>
              <span className="text-xs text-slate-400">CLV Beat Rate</span>
            </div>
            <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-slate-800/90">
              <div className="h-full w-[74.2%] rounded-full bg-gradient-to-r from-blue-600 via-sky-400 to-cyan-300 shadow-[0_0_16px_rgba(56,189,248,0.65)]" />
            </div>
            <p className="mt-2.5 text-[11px] text-slate-400">
              Goal: <span className="font-mono text-slate-200">60%</span> · Calibrated
            </p>
          </div>

          {/* Col 3: Execution Gate */}
          <div className="relative bg-[#070B14]/95 p-5">
            <span className="text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">
              Execution Gate
            </span>
            <div className="mt-2 rounded-xl border border-amber-400/25 bg-amber-500/[0.04] p-3.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
              <div className="flex items-center gap-2 font-mono text-lg font-bold tracking-wide text-amber-300">
                PAUSED
                <span className="h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_#fbbf24]" />
              </div>
              <p className="mt-1 text-xs text-slate-400">
                Standby for verified quotes
              </p>
            </div>
          </div>

          {/* Col 4: Feed Health */}
          <div className="relative flex flex-col justify-between bg-[#070B14]/95 p-5">
            <span className="text-[10px] font-semibold tracking-[0.16em] text-slate-400 uppercase">
              Feed Health
            </span>
            <div className="my-auto flex items-center justify-between rounded-xl border border-white/[0.06] bg-white/[0.02] px-3.5 py-2.5">
              <div className="flex items-center gap-2 text-xs">
                <span className="h-2 w-2 rounded-full bg-sky-400 shadow-[0_0_8px_#38bdf8]" />
                <span className="font-mono font-semibold text-slate-200">
                  ODDS STALE
                </span>
                <span className="text-slate-500">· 7d ago</span>
              </div>
              <button
                title="Refresh feed"
                className="flex h-7 w-7 items-center justify-center rounded-lg border border-sky-400/20 bg-sky-400/10 text-sky-300 transition hover:border-sky-400/40 hover:bg-sky-400/20 hover:text-white"
              >
                ↻
              </button>
            </div>
            <div className="font-mono text-[10px] text-slate-500">
              Root #178e29974bf8748c · Fail-Closed
            </div>
          </div>
        </section>

        {/* 4. DATA TABLE SHELL WITH LOCKED STICKY HEADER */}
        <div className="overflow-hidden rounded-2xl border border-sky-400/[0.14] bg-[#070B14]/90 shadow-[0_24px_60px_rgba(2,6,23,0.9)]">
          <div className="max-h-[680px] overflow-y-auto">
            <table className="w-full border-collapse text-left">
              <thead className="sticky top-0 z-20 border-b border-sky-400/[0.14] bg-[#060A12]/95 backdrop-blur-md">
                <tr className="font-mono text-[11px] font-semibold tracking-[0.12em] text-slate-400 uppercase">
                  <th className="py-3.5 pr-4 pl-6">Player / Driver</th>
                  <th className="px-4 py-3.5">Matchup</th>
                  <th className="px-4 py-3.5 text-center text-slate-500">
                    Book &amp; Status <span className="opacity-50">?</span>
                  </th>
                  <th className="px-4 py-3.5">
                    Model (Fair | Proj | 80% CI) <span className="opacity-50">?</span>
                  </th>
                  <th className="py-3.5 pr-6 pl-4 text-right text-slate-500">
                    Price Check / Edge <span className="opacity-50">?</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.05] text-sm">
                {SAMPLE_SLATE.map((row) => {
                  const isSimulating = simulatingId === row.id;
                  const parsedSim = parseFloat(simLine);
                  const simulatedEdge =
                    !isNaN(parsedSim) && parsedSim > 0
                      ? (((row.proj - parsedSim) / parsedSim) * 100).toFixed(1)
                      : null;

                  return (
                    <tr
                      key={row.id}
                      className="group transition-colors hover:bg-sky-500/[0.03]"
                    >
                      {/* Col 1: Player / Driver */}
                      <td className="py-4 pr-4 pl-6">
                        <div className="flex items-center gap-3.5">
                          <span className="rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-400">
                            {row.pos}
                          </span>
                          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-sky-400/25 bg-gradient-to-b from-sky-500/20 to-blue-900/20 font-mono text-xs font-bold text-sky-300">
                            {row.initials}
                          </div>
                          <div>
                            <div className="font-semibold text-white group-hover:text-sky-200">
                              {row.name}
                            </div>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                              <span className="font-mono text-[11px] text-slate-400">
                                {row.team} · {row.role}
                              </span>
                              {row.drivers.map((d) => (
                                <span
                                  key={d.label}
                                  className={`rounded-full border px-2 py-0.5 font-mono text-[10px] font-medium ${
                                    d.type === "alpha"
                                      ? "border-emerald-400/30 bg-emerald-500/15 text-emerald-300"
                                      : d.type === "volume"
                                      ? "border-sky-400/25 bg-sky-500/10 text-sky-300"
                                      : "border-indigo-400/25 bg-indigo-500/10 text-indigo-300"
                                  }`}
                                >
                                  {d.label} ({d.value})
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>
                      </td>

                      {/* Col 2: Matchup */}
                      <td className="px-4 py-4 font-mono text-xs text-slate-200">
                        <div className="flex items-center gap-2">
                          <span>{row.matchup}</span>
                          {row.env && (
                            <span className="rounded border border-sky-400/20 bg-sky-500/10 px-2 py-0.5 text-[10px] text-sky-300">
                              ▲ {row.env}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Col 3: Interactive Simulate Line Pill */}
                      <td className="px-4 py-4 text-center">
                        {isSimulating ? (
                          <div className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/40 bg-[#04070E] px-2.5 py-1">
                            <input
                              type="number"
                              step="0.5"
                              autoFocus
                              placeholder={row.fair.toFixed(1)}
                              value={simLine}
                              onChange={(e) => setSimLine(e.target.value)}
                              className="w-16 bg-transparent font-mono text-xs text-white focus:outline-none"
                            />
                            <button
                              onClick={() => {
                                setSimulatingId(null);
                                setSimLine("");
                              }}
                              className="text-xs text-slate-400 hover:text-white"
                            >
                              ✕
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => {
                              setSimulatingId(row.id);
                              setSimLine(row.fair.toFixed(1));
                            }}
                            className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-500/[0.06] px-3.5 py-1.5 font-mono text-xs text-slate-300 transition hover:border-sky-400/40 hover:bg-sky-500/15 hover:text-white"
                          >
                            <span className="text-sky-400">+</span> Simulate Line{" "}
                            <span className="text-sky-400/60">+</span>
                          </button>
                        )}
                      </td>

                      {/* Col 4: Sapphire SVG Density Curve & 80% CI */}
                      <td className="px-4 py-4">
                        <div className="w-64 font-mono tabular-nums">
                          <div className="mb-1 flex items-baseline justify-between text-xs">
                            <span className="text-slate-400">
                              FAIR{" "}
                              <strong className="text-slate-100">
                                {row.fair.toFixed(1)}
                              </strong>
                            </span>
                            <span className="text-slate-700">|</span>
                            <span className="text-slate-400">
                              PROJ{" "}
                              <strong className="text-sky-400 drop-shadow-[0_0_8px_rgba(56,189,248,0.4)]">
                                {row.proj.toFixed(1)}
                              </strong>
                            </span>
                          </div>
                          <div className="relative h-7 w-full">
                            <svg
                              viewBox="0 0 200 26"
                              className="h-full w-full overflow-visible"
                            >
                              <defs>
                                <linearGradient
                                  id={`sapphireGrad-${row.id}`}
                                  x1="0"
                                  y1="0"
                                  x2="0"
                                  y2="1"
                                >
                                  <stop
                                    offset="0%"
                                    stopColor="#38BDF8"
                                    stopOpacity="0.42"
                                  />
                                  <stop
                                    offset="100%"
                                    stopColor="#2563EB"
                                    stopOpacity="0.0"
                                  />
                                </linearGradient>
                              </defs>
                              <path
                                d="M 12 24 C 55 24, 78 3, 114 3 C 146 3, 165 24, 192 24 Z"
                                fill={`url(#sapphireGrad-${row.id})`}
                              />
                              <path
                                d="M 12 24 C 55 24, 78 3, 114 3 C 146 3, 165 24, 192 24"
                                fill="none"
                                stroke="#38BDF8"
                                strokeWidth="1.5"
                              />
                            </svg>
                            {/* CI Bar */}
                            <div className="absolute inset-x-0 bottom-0.5 h-1 rounded-full bg-slate-800">
                              <div className="absolute left-[22%] right-[16%] h-full rounded-full bg-gradient-to-r from-blue-600/60 via-sky-400 to-cyan-300" />
                              <span className="absolute left-[48%] -top-1 h-3 w-0.5 bg-white shadow-[0_0_6px_#fff]" />
                              <span className="absolute left-[58%] -top-1 h-3 w-3 -translate-x-1/2 rounded-full border-2 border-[#060A12] bg-sky-400 shadow-[0_0_10px_#38bdf8]" />
                            </div>
                          </div>
                          <div className="mt-1.5 flex items-center justify-between text-[10px] text-slate-400">
                            <span>
                              80%{" "}
                              <span className="rounded bg-sky-500/[0.08] px-1 py-0.5 text-slate-300">
                                {row.ciLow}–{row.ciHigh}y
                              </span>
                            </span>
                            <span className="text-slate-500">Model only</span>
                          </div>
                        </div>
                      </td>

                      {/* Col 5: Price Check / Simulated Edge */}
                      <td className="py-4 pr-6 pl-4 text-right font-mono text-xs tabular-nums">
                        {isSimulating && simulatedEdge ? (
                          <span
                            className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 font-semibold ${
                              parseFloat(simulatedEdge) > 0
                                ? "border-sky-400/30 bg-sky-500/15 text-sky-300"
                                : "border-rose-400/30 bg-rose-500/10 text-rose-300"
                            }`}
                          >
                            {parseFloat(simulatedEdge) > 0 ? "+" : ""}
                            {simulatedEdge}% Sim Edge
                          </span>
                        ) : (
                          <span className="text-slate-600">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}

