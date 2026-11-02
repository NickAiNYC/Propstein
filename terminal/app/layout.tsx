import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "PropStein Terminal — Slate Overview",
  description:
    "Fail-closed operator surface over the frozen Python model artifacts. No LLM in the decision path.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-layer-0 font-mono text-text-primary antialiased">
        {children}
      </body>
    </html>
  );
}
