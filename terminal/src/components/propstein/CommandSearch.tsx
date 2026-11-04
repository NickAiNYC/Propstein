"use client";

/* PropStein — unified command search (⌘K)
   One index: players · markets · research pages · destinations.
   Grouped results, keyboard navigation, recent queries,
   accessible announcements. */

import { useEffect, useMemo, useRef, useState } from "react";
import { Command } from "cmdk";
import { useApp } from "@/lib/propstein/router";
import { runSearch, SearchHit } from "@/lib/propstein/search";
import { LogoMark } from "./Logo";
import { cn } from "@/lib/utils";
import { Search, CornerDownLeft, ArrowUp, ArrowDown, FileQuestion } from "lucide-react";

const GROUP_ORDER: SearchHit["group"][] = ["Players", "Markets", "Research", "Go to"];

export function CommandSearch() {
  const { searchOpen, setSearchOpen, addRecentSearch, recentSearches } = useApp();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const hits = useMemo(() => runSearch(query), [query]);
  const grouped = useMemo(() => {
    const map = new Map<string, SearchHit[]>();
    for (const g of GROUP_ORDER) map.set(g, []);
    for (const hit of hits) map.get(hit.group)?.push(hit);
    return map;
  }, [hits]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setSearchOpen(!searchOpen);
      }
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [searchOpen, setSearchOpen]);

  useEffect(() => {
    if (!searchOpen) {
      setQuery("");
      setActiveIndex(0);
    }
  }, [searchOpen]);

  useEffect(() => setActiveIndex(0), [query]);

  const go = (hit: SearchHit) => {
    if (query.trim()) addRecentSearch(query.trim());
    setSearchOpen(false);
    window.location.hash = hit.target.slice(1);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, hits.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const hit = hits[activeIndex];
      if (hit) go(hit);
    }
  };

  if (!searchOpen) return null;

  let flatIndex = -1;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-start justify-center bg-black/60 px-4 pt-[12vh] backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-label="Search PropStein"
      onClick={(e) => {
        if (e.target === e.currentTarget) setSearchOpen(false);
      }}
    >
      <div
        className="w-full max-w-[560px] overflow-hidden rounded-[4px] border border-hairline bg-popover shadow-2xl shadow-black/50"
        onKeyDown={onKeyDown}
      >
        {/* input */}
        <div className="flex items-center gap-2.5 border-b border-hairline px-4">
          <Search className="h-4 w-4 shrink-0 text-text-muted" aria-hidden />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search players, markets, research…"
            aria-label="Search query"
            aria-controls="command-search-results"
            className="h-12 flex-1 bg-transparent text-sm text-text outline-none placeholder:text-text-muted"
          />
          <kbd className="rounded-[2px] border border-hairline bg-workspace px-1.5 py-0.5 font-data text-[10px] text-text-muted">
            ESC
          </kbd>
        </div>

        {/* results */}
        <div ref={listRef} className="max-h-[52vh] overflow-y-auto p-2" role="listbox" id="command-search-results">
          {query.trim() === "" ? (
            <div className="p-2">
              {recentSearches.length > 0 ? (
                <>
                  <p className="label-micro px-2 pb-1.5 pt-1">Recent</p>
                  {recentSearches.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setQuery(q)}
                      className="flex w-full items-center gap-2.5 rounded-[3px] px-2 py-2 text-left text-[13px] text-text transition-colors hover:bg-nav/70"
                    >
                      <Search className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                      {q}
                    </button>
                  ))}
                </>
              ) : null}
              <p className="label-micro px-2 pb-1.5 pt-3">Suggested</p>
              {["Justin Jefferson", "receiving yards", "calibration"].map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setQuery(q)}
                  className="flex w-full items-center gap-2.5 rounded-[3px] px-2 py-2 text-left text-[13px] text-text transition-colors hover:bg-nav/70"
                >
                  <Search className="h-3.5 w-3.5 text-text-muted" aria-hidden />
                  {q}
                </button>
              ))}
            </div>
          ) : hits.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
              <FileQuestion className="h-5 w-5 text-text-muted" aria-hidden />
              <p className="text-sm text-text">No results for “{query}”</p>
              <p className="text-xs text-text-muted">
                Try a player name, a team, “receptions”, “yards”, or “audit”
              </p>
            </div>
          ) : (
            GROUP_ORDER.map((group) => {
              const items = grouped.get(group)!;
              if (items.length === 0) return null;
              return (
                <div key={group} className="mb-1 last:mb-0">
                  <p className="label-micro px-2 pb-1 pt-2">{group}</p>
                  {items.map((hit) => {
                    flatIndex++;
                    const idx = flatIndex;
                    const active = idx === activeIndex;
                    return (
                      <button
                        key={hit.id}
                        type="button"
                        role="option"
                        aria-selected={active}
                        onMouseEnter={() => setActiveIndex(idx)}
                        onClick={() => go(hit)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-[3px] px-2 py-2 text-left transition-colors",
                          active ? "bg-sapphire-surface" : "hover:bg-nav/60"
                        )}
                      >
                        <span className="min-w-0 flex-1">
                          <span className={cn("block truncate text-[13px]", active ? "text-sapphire-hover" : "text-text")}>
                            {hit.title}
                          </span>
                          <span className="block truncate text-[11px] text-text-muted">{hit.subtitle}</span>
                        </span>
                        {active ? (
                          <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-sapphire" aria-hidden />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>

        {/* footer */}
        <div className="flex items-center gap-4 border-t border-hairline bg-workspace px-4 py-2 text-[10px] text-text-muted">
          <span className="flex items-center gap-1">
            <ArrowUp className="h-3 w-3" aria-hidden />
            <ArrowDown className="h-3 w-3" aria-hidden />
            navigate
          </span>
          <span className="flex items-center gap-1">
            <CornerDownLeft className="h-3 w-3" aria-hidden />
            open
          </span>
          <span className="ml-auto flex items-center gap-1.5">
            <LogoMark size={11} />
            PropStein unified search
          </span>
        </div>
        <p aria-live="polite" className="sr-only">
          {hits.length} results for {query}
        </p>
      </div>
    </div>
  );
}
