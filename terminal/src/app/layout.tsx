import type { Metadata, Viewport } from "next";
import { Geist, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

/* Geist — interface, navigation, headings, player names, descriptions */
const geist = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
});

/* IBM Plex Mono — quantitative measurements, probabilities, odds, timestamps */
const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: {
    default: "PropStein — Distributional Player-Prop Research Terminal",
    template: "%s · PropStein",
  },
  description:
    "PropStein models player-prop markets as full probability distributions — Negative Binomial counts, Gamma yards per reception — with median fair lines, projected volume, captured market quotes, and public full-board evaluation.",
  applicationName: "PropStein",
  icons: {
    icon: [
      { url: "/brand/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/brand/icon-32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: [{ url: "/brand/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
  openGraph: {
    title: "PropStein — Research Terminal",
    description:
      "Fair lines from full probability distributions. Captured market quotes with provenance. Public full-board evaluation.",
    siteName: "PropStein",
    images: [{ url: "/brand/og.png", width: 1200, height: 630, type: "image/png" }],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "PropStein — Research Terminal",
    description:
      "Fair lines from full probability distributions. Captured market quotes with provenance. Public full-board evaluation.",
    images: [{ url: "/brand/og.png", width: 1200, height: 630, type: "image/png" }],
  },
  other: {
    "format-detection": "telephone=no",
  },
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0B0D11",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${geist.variable} ${plexMono.variable} bg-canvas text-text antialiased`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
