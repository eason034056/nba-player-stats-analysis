/**
 * layout.tsx - Root layout
 *
 * No-Vig shell. Instrument Sans is the UI face. JetBrains Mono is the
 * face for numbers. The page canvas is #EEEEEE.
 */

import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/AppShell";

const sans = localFont({
  src: [
    { path: "./fonts/InstrumentSans[wght].woff2", weight: "400", style: "normal" },
    { path: "./fonts/InstrumentSans[wght].woff2", weight: "500", style: "normal" },
    { path: "./fonts/InstrumentSans[wght].woff2", weight: "600", style: "normal" },
    { path: "./fonts/InstrumentSans[wght].woff2", weight: "700", style: "normal" },
  ],
  display: "swap",
  adjustFontFallback: "Arial",
  variable: "--font-sans",
  declarations: [{ prop: "font-stretch", value: "100%" }],
});

const mono = localFont({
  src: [
    { path: "./fonts/JetBrainsMono[wght].woff2", weight: "500", style: "normal" },
    { path: "./fonts/JetBrainsMono[wght].woff2", weight: "600", style: "normal" },
    { path: "./fonts/JetBrainsMono[wght].woff2", weight: "700", style: "normal" },
  ],
  display: "swap",
  adjustFontFallback: "Arial",
  variable: "--font-mono",
});

/**
 * Metadata Settings
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 5,
  viewportFit: "cover",
  themeColor: "#EEEEEE",
};

export const metadata: Metadata = {
  title: {
    default: "No-Vig NBA | No-Vig Probability Calculator",
    template: "%s | No-Vig NBA",
  },
  description:
    "Calculate vig-free probabilities for NBA player score props, remove bookmaker margin, and obtain fair market probability estimates.",
  keywords: [
    "NBA",
    "no-vig",
    "vig-free",
    "odds",
    "probability",
    "player score",
    "props",
    "betting",
  ],
  authors: [{ name: "No-Vig NBA" }],
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "No-Vig NBA",
  },
  icons: {
    icon: "/icon.svg",
    apple: "/icon.svg",
  },
};

/**
 * Root Layout Component
 * 
 * Minimalist design: solid color background, no decoration
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className={`${sans.variable} ${mono.variable} font-sans`}>
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
