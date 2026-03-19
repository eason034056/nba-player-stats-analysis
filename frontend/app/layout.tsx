/**
 * layout.tsx - Root Layout (Minimalist Version)
 * 
 * Root layout file for Next.js App Router
 * 
 * Design Philosophy:
 * - Pure beige background (#FFF2DF)
 * - No decorative elements
 * - Clean structure
 */

import type { Metadata } from "next";
import { Cormorant_Garamond, Manrope } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import { Navbar } from "@/components/Navbar";

const sans = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
});

const display = Cormorant_Garamond({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-display",
});

/**
 * Metadata Settings
 */
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
  icons: {
    icon: "/favicon.ico",
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
      <body className={`${sans.variable} ${display.variable}`}>
        <Providers>
          <Navbar />

          <main className="page-shell min-h-screen pt-28">
            {children}
          </main>

          <footer className="footer">
            <div className="mx-auto max-w-6xl px-6">
              <div className="rounded-[28px] border border-white/8 bg-white/4 px-6 py-6 backdrop-blur-xl">
                <p className="text-sm text-dark mb-2">
                  No-Vig NBA organizes schedules, probabilities, projections, and historical performances into a more readable analytical experience.
                </p>
                <p className="text-xs text-light">
                  The content on this site is for informational and research purposes only and does not constitute betting advice. Live odds and data may be delayed or missing; please refer to official sources for accuracy.
                </p>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
