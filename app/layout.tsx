// app/layout.tsx
import React from "react";
import type { Metadata } from "next";
import { TerminalHeader } from "@/src/components/TerminalHeader";

export const metadata: Metadata = {
  title: "PropWire Terminal | Institutional Sports Prop Analytics",
  description:
    "Cryptographically verified, fail-closed quantitative NFL player props research terminal and CLV ledger.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#080d14] text-slate-100 font-mono antialiased selection:bg-emerald-500/30 selection:text-emerald-300">
        <TerminalHeader
          activeCount={14}
          latencySeconds={12}
          onOpenPro={() => {}}
          onOpenLedger={() => {}}
          onOpenAudit={() => {}}
        />
        <main className="w-full">{children}</main>
      </body>
    </html>
  );
}
