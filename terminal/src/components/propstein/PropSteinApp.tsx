"use client";

/* PropStein — 2027 redesign application root.
   Single deployed route; hash-based view routing with
   deep links. All views share the two-level shell. */

import { Suspense, useEffect, useState } from "react";
import { useApp, initFromHash, defaultMarketFor } from "@/lib/propstein/router";
import { AppShell } from "./AppShell";
import { OverviewPage } from "./OverviewPage";
import { MarketBoard } from "./MarketBoard";
import { PlayerResearchPage } from "./PlayerResearchPage";
import { PerformancePage } from "./PerformancePage";
import { MethodologyPage, ValueBoundariesPage } from "./PublicPages";
import { PlayerIndexPage, SavedPage } from "./IndexPages";
import { Panel } from "./primitives";
import { LogoMark } from "./Logo";
import { WifiOff } from "lucide-react";

let initialized = false;

/** Terminal skeleton — mirrors the workspace layout while data initializes. */
function AppSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-busy="true" aria-label="Loading research terminal">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-2">
          <LogoMark size={26} />
          <div className="h-2.5 w-40 animate-pulse rounded bg-workscreen" />
          <div className="h-7 w-72 animate-pulse rounded bg-workscreen" />
        </div>
      </div>
      <div className="grid h-20 grid-cols-2 gap-px overflow-hidden rounded-[4px] border border-hairline bg-hairline md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="bg-workspace" />
        ))}
      </div>
      <div className="h-64 animate-pulse rounded-[4px] border border-hairline bg-panel" />
      <div className="h-40 animate-pulse rounded-[4px] border border-hairline bg-panel" />
    </div>
  );
}

/** Offline state — snapshot terminals degrade visibly, never silently. */
function OfflineBanner() {
  const [offline, setOffline] = useState(false);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  if (!offline) return null;
  return (
    <div
      role="status"
      className="hairline-b flex items-center gap-2 border-hairline bg-caution/10 px-4 py-2 text-xs text-caution lg:px-6"
    >
      <WifiOff className="h-3.5 w-3.5" aria-hidden />
      Offline — showing the last captured snapshot. No data is being refreshed.
    </div>
  );
}

export function PropSteinApp() {
  const route = useApp((s) => s.route);

  useEffect(() => {
    if (!initialized && typeof window !== "undefined") {
      initialized = true;
      initFromHash();
    }
  }, []);

  // view title for document + focus management
  useEffect(() => {
    const titles: Record<string, string> = {
      overview: "Overview",
      markets: "Market board",
      players: "Player research",
      player: "Player research",
      performance: "Performance & audit",
      methodology: "Methodology",
      boundaries: "Value boundaries",
      saved: "Saved research",
      status404: "Not found",
    };
    document.title = `${titles[route.view] ?? "Research"} · PropStein`;
  }, [route.view]);

  return (
    <AppShell>
      <OfflineBanner />
      <Suspense fallback={<AppSkeleton />}>
        {route.view === "overview" ? <OverviewPage /> : null}
        {route.view === "markets" ? <MarketBoard /> : null}
        {route.view === "players" ? <PlayerIndexPage /> : null}
        {route.view === "player" && route.playerId ? (
          <PlayerResearchPage
            playerId={route.playerId}
            market={route.market ?? defaultMarketFor(route.playerId)}
          />
        ) : null}
        {route.view === "performance" ? <PerformancePage /> : null}
        {route.view === "methodology" ? <MethodologyPage /> : null}
        {route.view === "boundaries" ? <ValueBoundariesPage /> : null}
        {route.view === "saved" ? <SavedPage /> : null}
        {route.view === "status404" ? (
          <Panel className="mx-auto mt-16 max-w-md p-10 text-center">
            <p className="font-display text-lg font-semibold text-text">Page not found</p>
            <p className="mt-2 text-xs leading-relaxed text-text-muted">
              The research page you followed does not exist in this snapshot.
            </p>
          </Panel>
        ) : null}
      </Suspense>
    </AppShell>
  );
}
