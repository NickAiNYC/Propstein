import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Propstein — Live Sports Prop Terminal",
  description:
    "Zero-cost real-time sports prop intelligence: live NBA/NFL/NHL scores, player form, and model edges with EV, fair odds and Kelly staking. Free tier gets the direction; Pro gets the number.",
  keywords: ["sports props", "NBA", "NFL", "NHL", "expected value", "Kelly criterion", "live scores"],
  icons: {
    icon: "/favicon.svg",
  },
  openGraph: {
    title: "Propstein — Live Sports Prop Terminal",
    description: "Live scores, player form, and model edges. Free gets the direction, Pro gets the number.",
    siteName: "Propstein",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
