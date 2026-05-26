/**
 * wnba/layout.tsx — WNBA route-segment metadata override.
 *
 * SPO-60: every `/wnba/*` page rendered with the root layout's NBA title
 * because the root `metadata.title.default` is "No-Vig NBA". WNBA pages
 * are client components and cannot export their own `metadata`, so we
 * piggy-back on Next.js App Router route-segment metadata: any layout
 * deeper in the tree replaces matching keys from the root layout.
 *
 * Scope is deliberately narrow — title + description only. The root
 * layout still owns fonts, providers, navbar, footer, icons, manifest,
 * keywords, and viewport (none of which differ between leagues).
 */

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: {
    default: "No-Vig WNBA | No-Vig Probability Calculator",
    template: "%s | No-Vig WNBA",
  },
  description:
    "Calculate vig-free probabilities for WNBA player score props, remove bookmaker margin, and obtain fair market probability estimates.",
};

export default function WNBALayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
