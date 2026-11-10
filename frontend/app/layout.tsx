/**
 * layout.tsx - Root layout
 *
 * No-Vig shell. Instrument Sans is the UI face. JetBrains Mono is the
 * face for numbers. The page canvas is #EEEEEE.
 */

import type { Metadata, Viewport } from "next";
import { Instrument_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/AppShell";

const sans = Instrument_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
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
