"use client";

/* ============================================================
   PropStein — brand assets
   The lightning-P mark and the PROPSTEIN lockup are the user's
   approved brand artwork (extracted losslessly from the source
   brand image with transparent backgrounds). One source of
   truth for every brand surface: sidebar, mobile bar, footer,
   dialogs, splash, favicon.
   ============================================================ */

import Image from "next/image";
import lockupPng from "../../../public/brand/lockup.png";
import markPng from "../../../public/brand/mark.png";
import { cn } from "@/lib/utils";

/** The lightning-P mark. Nearly square (204×201). */
export function LogoMark({
  size = 24,
  className,
  priority = false,
}: {
  size?: number;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src={markPng}
      alt=""
      width={204}
      height={201}
      priority={priority}
      className={cn("select-none", className)}
      style={{ height: size, width: "auto" }}
    />
  );
}

/** Full PROPSTEIN wordmark lockup (745×209) with the oversized lightning-P. */
export function LogoLockup({
  height = 22,
  className,
  priority = false,
}: {
  height?: number;
  className?: string;
  priority?: boolean;
}) {
  return (
    <Image
      src={lockupPng}
      alt="PropStein"
      width={745}
      height={209}
      priority={priority}
      className={cn("select-none", className)}
      style={{ height, width: "auto" }}
    />
  );
}

/** Sidebar brand block — lockup + understated descriptor. */
export function BrandBlock({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex select-none items-center gap-2.5">
      <LogoMark size={compact ? 26 : 30} priority />
      <span className="flex flex-col gap-1 leading-none">
        <LogoLockup height={compact ? 17 : 19} priority />
        <span className="text-[9px] font-medium tracking-[0.16em] text-text-muted">
          RESEARCH TERMINAL
        </span>
      </span>
    </span>
  );
}

/** Mark on a graphite tile — empty states, splash, account surfaces. */
export function BrandTile({ size = 44, className }: { size?: number; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-flex items-center justify-center rounded-[10px] border border-hairline bg-elevated",
        className
      )}
      style={{ width: size, height: size }}
    >
      <LogoMark size={size * 0.62} />
    </span>
  );
}
