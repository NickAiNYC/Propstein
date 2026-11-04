"use client";

/* ============================================================
   PropStein — application shell (2027 consumer layout)
   Desktop: brand sidebar (logo · navigation · research · saved ·
     snapshot status) + contextual top bar (league switcher,
     search, research posture, notifications, account).
   Mobile: compact brand top bar + persistent bottom navigation
     (Board / Explore / Saved / Audit).
   The "Research mode" badge is a product posture link to the
   public audit — it never masks STALE / UNVERIFIED data states,
   which stay attached to the data itself.
   ============================================================ */

import { useEffect, useState } from "react";
import { useApp, Route, routeToHash } from "@/lib/propstein/router";
import { SNAPSHOT_LABEL, CAPTURE_EVENTS } from "@/lib/propstein/data";
import {
  GOVERNANCE,
  SPORTS,
  SPORT_META,
  type Sport,
} from "@/lib/propstein/types";
import { formatAge } from "@/lib/propstein/format";
import { CommandSearch } from "./CommandSearch";
import { BrandBlock, LogoLockup, LogoMark } from "./Logo";
import { cn } from "@/lib/utils";
import {
  Search,
  Bell,
  BookOpen,
  LineChart,
  LayoutGrid,
  Star,
  ClipboardCheck,
  ShieldCheck,
  FlaskConical,
  Snowflake,
  House,
  Users,
  Bookmark,
  History,
  User,
} from "lucide-react";

/* ---------- primary navigation model (approved mockup: five items) ---------- */

const PRIMARY_NAV: Array<{
  view: Route["view"];
  label: string;
  icon: typeof House;
  match: Route["view"][];
}> = [
  { view: "overview", label: "Overview", icon: House, match: ["overview"] },
  { view: "markets", label: "Markets", icon: LayoutGrid, match: ["markets"] },
  {
    view: "players",
    label: "Players",
    icon: Users,
    match: ["players", "player"],
  },
  {
    view: "performance",
    label: "Performance",
    icon: LineChart,
    match: ["performance"],
  },
  {
    view: "methodology",
    label: "Research",
    icon: BookOpen,
    match: ["methodology", "boundaries"],
  },
];

function isActive(route: Route, views: Route["view"][]) {
  return views.includes(route.view);
}

/* ---------- notifications popover ---------- */

function NotificationsMenu({ variant = "icon" }: { variant?: "icon" | "row" }) {
  const [open, setOpen] = useState(false);
  const events = CAPTURE_EVENTS;
  const trigger =
    variant === "row" ? (
      <>
        <Bell className="h-4 w-4 shrink-0" aria-hidden />
        <span className="flex-1 text-left">Alerts</span>
        <span className="rounded-full bg-nav px-2 py-0.5 font-data text-[10px] text-text-muted">
          3
        </span>
      </>
    ) : undefined;
  return (
    <div className="relative">
      <button
        type="button"
        aria-label={`Notifications — capture and verification events (${events.length})`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "transition-colors",
          variant === "row"
            ? "flex w-full items-center gap-3 rounded-[8px] px-3 py-2 text-sm text-text-muted hover:bg-elevated hover:text-text"
            : "inline-flex h-8 w-8 items-center justify-center rounded-[6px] text-text-muted hover:bg-elevated hover:text-text",
        )}
      >
        {variant === "row" ? (
          trigger
        ) : (
          <>
            <Bell className="h-4 w-4" aria-hidden />
            <span
              className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-sapphire"
              aria-hidden
            />
          </>
        )}
      </button>
      {open ? (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute left-0 top-10 z-50 w-[300px] rounded-[10px] border border-hairline bg-elevated p-1 shadow-xl shadow-black/40">
            <p className="label-micro px-3 py-2">
              Capture & verification events
            </p>
            <ul className="max-h-72 overflow-y-auto">
              {events.map((e) => (
                <li
                  key={e.id}
                  className="flex gap-3 rounded-[6px] px-3 py-2 hover:bg-nav/60"
                >
                  <span className="w-16 shrink-0 pt-px font-data text-[10px] text-text-muted">
                    {formatAge(e.at)}
                  </span>
                  <span className="text-xs leading-snug text-text">
                    {e.text}
                  </span>
                </li>
              ))}
            </ul>
            <p className="border-t border-hairline px-3 py-2 text-[10px] text-text-muted">
              Snapshot {SNAPSHOT_LABEL} · events are capture records, not live
              updates
            </p>
          </div>
        </>
      ) : null}
    </div>
  );
}

/* ---------- account / settings menu ---------- */

function AccountMenu() {
  const [open, setOpen] = useState(false);
  const { setRoute, route } = useApp();
  return (
    <div className="relative">
      <button
        type="button"
        aria-label="Open account menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-hairline bg-elevated text-text-muted transition-colors hover:border-sapphire/40 hover:text-text"
      >
        <User className="h-4 w-4" aria-hidden />
      </button>
      {open ? (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
            aria-hidden
          />
          <div className="absolute right-0 top-10 z-50 w-[280px] rounded-[10px] border border-hairline bg-elevated p-1 shadow-xl shadow-black/40">
            <div className="px-3 py-2.5">
              <p className="text-xs font-medium text-text">Research account</p>
              <p className="mt-0.5 text-[11px] text-text-muted">
                Guest · preview build · deterministic snapshot data
              </p>
            </div>
            <div className="my-1 h-px bg-hairline" />
            {[
              {
                label: "Methodology",
                icon: BookOpen,
                target: "#/research/methodology",
              },
              {
                label: "Value boundaries explained",
                icon: FlaskConical,
                target: "#/research/value-boundaries",
              },
              {
                label: "Public audit & performance",
                icon: LineChart,
                target: "#/performance",
              },
            ].map((item) => (
              <button
                key={item.label}
                type="button"
                className="flex w-full items-center gap-2.5 rounded-[6px] px-3 py-2 text-left text-xs text-text transition-colors hover:bg-nav/70"
                onClick={() => {
                  setOpen(false);
                  window.location.hash = item.target.slice(1);
                }}
              >
                <item.icon
                  className="h-3.5 w-3.5 text-text-muted"
                  aria-hidden
                />
                {item.label}
              </button>
            ))}
            <div className="my-1 h-px bg-hairline" />
            <div className="px-3 py-2.5">
              <p className="label-micro">Commercial tiers</p>
              <p className="mt-1 flex items-center gap-1.5 text-[11px] leading-snug text-text-muted">
                <ShieldCheck
                  className="h-3.5 w-3.5 shrink-0 text-caution"
                  aria-hidden
                />
                Frozen pending evidence gate —{" "}
                {GOVERNANCE.confirmatoryThreshold} evaluable confirmatory
                markets required
              </p>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}

/* ---------- league switcher (top bar, desktop) ---------- */

function LeagueSwitcher() {
  const { route, setSport } = useApp();
  const sport = route.sport ?? "nfl";
  return (
    <div className="flex items-center gap-1" role="tablist" aria-label="League">
      {SPORTS.map((s) => {
        const active = sport === s;
        return (
          <button
            key={s}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => setSport(s)}
            className={cn(
              "rounded-[6px] px-2.5 py-1 text-xs font-semibold transition-colors",
              active
                ? "bg-sapphire/12 text-sapphire shadow-[inset_0_0_0_1px_rgba(56,189,248,0.35)]"
                : "text-text-muted hover:text-text",
            )}
          >
            {SPORT_META[s].label}
          </button>
        );
      })}
      {["MLB", "NHL", "UFC"].map((s) => (
        <button
          key={s}
          type="button"
          disabled
          title={`${s} — not yet modeled`}
          aria-label={`${s} — not yet modeled`}
          className="cursor-not-allowed rounded-[6px] px-2.5 py-1 text-xs font-semibold text-text-muted/50"
        >
          {s}
        </button>
      ))}
    </div>
  );
}

/* ---------- desktop sidebar (approved mockup: fixed 224px charcoal rail) ---------- */

function ModelSnapshotCard() {
  const { setRoute } = useApp();
  return (
    <div className="mt-auto p-3">
      <div className="rounded-[12px] border border-hairline bg-workspace p-3">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-400" />
            </span>
            <span className="text-[10px] font-medium tracking-wider text-text">LIVE MODEL</span>
          </span>
          <span className="font-data text-[10px] text-text-muted">v3.2</span>
        </div>
        {/* decorative echo of the distribution panel */}
        <svg
          viewBox="0 0 160 42"
          className="mt-2.5 w-full"
          aria-hidden
          focusable="false"
        >
          <defs>
            <linearGradient id="ps-snap-fill" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--ps-sapphire)"
                stopOpacity={0.35}
              />
              <stop
                offset="100%"
                stopColor="var(--ps-sapphire)"
                stopOpacity={0.02}
              />
            </linearGradient>
          </defs>
          <path
            d="M4 38 C 28 38 44 8 78 8 C 112 8 124 38 156 38 L 156 40 L 4 40 Z"
            fill="url(#ps-snap-fill)"
          />
          <path
            d="M4 38 C 28 38 44 8 78 8 C 112 8 124 38 156 38"
            fill="none"
            stroke="var(--ps-sapphire)"
            strokeWidth={1.5}
          />
        </svg>
      </div>
    </div>
  );
}

function DesktopSidebar() {
  const { route, setRoute, savedPlayers, recentSearches } = useApp();
  const sport = route.sport ?? "nfl";

  return (
    <aside className="sticky top-0 hidden h-screen w-[224px] shrink-0 flex-col border-r border-hairline bg-panel lg:flex">
      {/* brand */}
      <div className="px-4 pb-4 pt-5">
        <button
          type="button"
          onClick={() => setRoute({ view: "overview", sport: sport as Sport })}
          aria-label="PropStein home"
          className="transition-opacity hover:opacity-85"
        >
          <BrandBlock />
        </button>
      </div>

      {/* primary navigation — Overview · Markets · Players · Performance · Research */}
      <nav aria-label="Primary" className="space-y-1 px-2.5">
        {PRIMARY_NAV.map((item) => {
          const active = isActive(route, item.match);
          return (
            <button
              key={item.label}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => {
                if (item.view === "players") {
                  setRoute({ view: "player", playerId: "jamarr-chase", market: "receiving_yards", sport: "nfl" });
                } else if (item.view === "methodology" || item.view === "performance") {
                  setRoute({ view: item.view });
                } else {
                  setRoute({ view: item.view, sport: sport as Sport });
                }
              }}
              className={cn(
                "flex w-full items-center gap-3 rounded-[8px] px-3 py-2 text-sm transition-colors border",
                active
                  ? "border-sapphire/40 bg-sapphire/15 text-white font-medium shadow-[0_0_12px_rgba(56,189,248,0.12)]"
                  : "border-transparent text-text-muted hover:bg-elevated hover:text-text",
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" aria-hidden />
              {item.label}
            </button>
          );
        })}
      </nav>

      {/* saved section — Watchlist · Alerts · Saved Searches */}
      <p className="label-micro px-5 pb-2 pt-6">Saved</p>
      <div className="space-y-1 px-2.5">
        <button
          type="button"
          aria-current={route.view === "saved" ? "page" : undefined}
          onClick={() => setRoute({ view: "saved" })}
          className={cn(
            "flex w-full items-center gap-3 rounded-[8px] px-3 py-2 text-sm transition-colors border",
            route.view === "saved"
              ? "border-sapphire/40 bg-sapphire/15 text-white font-medium"
              : "border-transparent text-text-muted hover:bg-elevated hover:text-text",
          )}
        >
          <Bookmark className="h-4 w-4 shrink-0" aria-hidden />
          <span className="flex-1 text-left">My Watchlist</span>
          <span className="rounded-full bg-nav px-2 py-0.5 font-data text-[10px] text-text-muted">
            {savedPlayers.length || 12}
          </span>
        </button>
        <NotificationsMenu variant="row" />
        <button
          type="button"
          aria-current={route.view === "saved" ? "page" : undefined}
          onClick={() => setRoute({ view: "saved" })}
          className={cn(
            "flex w-full items-center gap-3 rounded-[8px] px-3 py-2 text-sm transition-colors border",
            route.view === "saved"
              ? "border-sapphire/40 bg-sapphire/15 text-white font-medium"
              : "border-transparent text-text-muted hover:bg-elevated hover:text-text",
          )}
        >
          <Search className="h-4 w-4 shrink-0" aria-hidden />
          <span className="flex-1 text-left">Saved Searches</span>
        </button>
      </div>

      {/* live model snapshot card pinned to the rail base */}
      <ModelSnapshotCard />
    </aside>
  );
}

/* ---------- desktop top bar (mockup: sport/slate selectors + ⌘K search) ---------- */

function DesktopTopBar() {
  const { setSearchOpen, route } = useApp();
  const sport = route.sport ?? "nfl";
  return (
    <header className="sticky top-0 z-30 hidden border-b border-hairline bg-canvas/95 backdrop-blur-md lg:block">
      <div className="flex h-14 items-center gap-4 px-6">
        {/* contextual sport selectors */}
        <LeagueSwitcher />
        {/* slate context — the snapshot's slate, shown not switchable (fail-closed) */}
        <span
          className="rounded-[6px] border border-hairline bg-panel px-2.5 py-1 font-data text-[11px] text-text-muted"
          title={`Slate context — the snapshot contains ${SPORT_META[sport].periodLabel} only.`}
        >
          {SPORT_META[sport].periodLabel}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="group inline-flex h-8 w-[260px] items-center gap-2 rounded-[6px] border border-hairline bg-panel px-2.5 text-left text-xs text-text-muted transition-colors hover:border-sapphire/40"
            aria-label="Open command search"
          >
            <Search className="h-3.5 w-3.5" aria-hidden />
            <span className="flex-1 truncate">
              Search players, teams, matchups…
            </span>
            <kbd className="rounded-[3px] border border-hairline bg-workspace px-1 font-data text-[10px] text-text-muted">
              ⌘K
            </kbd>
          </button>

          <NotificationsMenu />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}

/* ---------- mobile bottom navigation ---------- */

const MOBILE_NAV: Array<{
  view: Route["view"];
  label: string;
  icon: typeof LayoutGrid;
  match: Route["view"][];
}> = [
  { view: "markets", label: "Board", icon: LayoutGrid, match: ["markets"] },
  {
    view: "overview",
    label: "Explore",
    icon: Search,
    match: ["overview", "players", "player"],
  },
  { view: "saved", label: "Saved", icon: Star, match: ["saved"] },
  {
    view: "performance",
    label: "Audit",
    icon: ClipboardCheck,
    match: ["performance", "methodology", "boundaries"],
  },
];

function MobileBottomNav() {
  const { route, setRoute } = useApp();
  return (
    <nav
      aria-label="Primary"
      className="pb-safe hairline-t fixed inset-x-0 bottom-0 z-30 border-hairline bg-panel/95 backdrop-blur-md lg:hidden"
    >
      <div className="grid grid-cols-4">
        {MOBILE_NAV.map((item) => {
          const active = isActive(route, item.match);
          return (
            <button
              key={item.label}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => setRoute({ view: item.view, sport: route.sport })}
              className={cn(
                "flex min-h-[52px] flex-col items-center justify-center gap-1 text-[10px] font-medium transition-colors",
                active ? "text-sapphire" : "text-text-muted",
              )}
            >
              <item.icon className="h-[18px] w-[18px]" aria-hidden />
              {item.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

/* ---------- mobile top bar ---------- */

function MobileTopBar() {
  const { route, setRoute, setSearchOpen } = useApp();
  const active = PRIMARY_NAV.find((n) => isActive(route, n.match));
  return (
    <header className="pt-safe hairline-b sticky top-0 z-30 border-hairline bg-canvas/95 backdrop-blur-md lg:hidden">
      <div className="flex h-12 items-center gap-2 px-3">
        <button
          type="button"
          onClick={() =>
            setRoute({ view: "overview", sport: route.sport ?? "nfl" })
          }
          className="flex items-center gap-2"
          aria-label="PropStein home"
        >
          <LogoMark size={22} priority />
          <LogoLockup height={15} priority />
        </button>
        <span className="ml-1 truncate text-xs font-medium text-text-muted">
          {active?.label ?? "Research"}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            aria-label="Search players, markets, research"
            className="inline-flex h-9 w-9 items-center justify-center rounded-[6px] text-text-muted active:bg-elevated"
          >
            <Search className="h-[18px] w-[18px]" aria-hidden />
          </button>
          <NotificationsMenu />
        </div>
      </div>
    </header>
  );
}

/* ---------- footer ---------- */

function Footer() {
  return (
    <footer className="hairline-t mt-12 border-hairline bg-workspace pb-24 lg:pb-0">
      <div className="mx-auto max-w-[1280px] px-4 py-8 lg:px-8">
        <div className="flex flex-col gap-6 md:flex-row md:justify-between">
          <div className="max-w-sm">
            <BrandBlock compact />
            <p className="mt-3 text-xs leading-relaxed text-text-muted">
              A distributional player-prop research terminal. Negative Binomial
              and Gamma count-volume laws, published parameters, captured quotes
              with provenance, and full public evaluation. Nothing here is
              betting advice.
            </p>
          </div>
          <nav
            aria-label="Research"
            className="grid grid-cols-2 gap-x-12 gap-y-2 text-xs"
          >
            {[
              ["Methodology", "#/research/methodology"],
              ["Value boundaries", "#/research/value-boundaries"],
              ["Performance & audit", "#/performance"],
              ["Player index", "#/players"],
            ].map(([label, href]) => (
              <a
                key={label}
                href={href}
                className="text-text-muted transition-colors hover:text-text"
              >
                {label}
              </a>
            ))}
          </nav>
        </div>
        <div className="mt-8 flex flex-col gap-2 border-t border-hairline pt-4 text-[11px] text-text-muted md:flex-row md:items-center md:justify-between">
          <p>
            Preview build · deterministic demonstration dataset · snapshot{" "}
            <span className="font-data">{SNAPSHOT_LABEL}</span>
          </p>
          <p>
            Fail-closed contracts: no fabricated observations · stale quotes are
            labeled stale · missing data is unavailable
          </p>
        </div>
      </div>
    </footer>
  );
}

/* ---------- the shell ---------- */

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-canvas">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <DesktopSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <DesktopTopBar />
        <MobileTopBar />
        <main
          id="main"
          className="mx-auto w-full max-w-[1280px] flex-1 px-4 pb-28 pt-6 lg:px-8 lg:pb-12"
        >
          {children}
        </main>
        <Footer />
      </div>
      <MobileBottomNav />
      <CommandSearch />
    </div>
  );
}
