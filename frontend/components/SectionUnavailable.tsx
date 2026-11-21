"use client";

import { Info } from "lucide-react";

/**
 * SectionUnavailable — labeled empty state for a section whose data is missing.
 */
interface SectionUnavailableProps {
  /** Small uppercase eyebrow — mirrors the real section's `section-eyebrow`. */
  eyebrow: string;
  /** Section heading. */
  title: string;
  /** One-line reason the data is not present. */
  message: string;
}

export function SectionUnavailable({
  eyebrow,
  title,
  message,
}: SectionUnavailableProps) {
  return (
    <div className="card">
      <p className="section-eyebrow">{eyebrow}</p>
      <h3 className="mt-2 text-lg font-semibold text-dark">{title}</h3>
      <div className="mt-4 flex items-start gap-3 rounded-[18px] border border-dark/10 bg-dark/[0.03] px-4 py-4 text-sm text-gray">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-light" />
        <span>{message}</span>
      </div>
    </div>
  );
}
