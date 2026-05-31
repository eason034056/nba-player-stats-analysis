"use client";

import { Info } from "lucide-react";

/**
 * SectionUnavailable — labeled "not available for <league>" empty state.
 *
 * SPO-83 Phase 0 convention (see docs/decisions/SPO-82/decision_20260531_wnba-parity-approach.md,
 * Decision 2): when a section exists in the reference design (NBA) but the
 * current league genuinely lacks the backing data (no projection endpoint, no
 * lineup ingestion, etc.), we DO NOT drop the section. Dropping it recreates
 * the structural drift this epic exists to fix. Instead we render this
 * placeholder in the same slot so the page keeps the same shape across leagues
 * and the data gap is explicit rather than silent.
 *
 * 💡 Centralizing the empty state in one component (rather than inlining a
 * <div> per gap) means every later phase — picks, home — reuses the exact same
 * wording and styling. That is the whole point of a "pattern-setting" slice.
 */
interface SectionUnavailableProps {
  /** Small uppercase eyebrow — mirrors the real section's `section-eyebrow`. */
  eyebrow: string;
  /** Section heading, kept identical to the supported-league version. */
  title: string;
  /** One-line reason the data is not present for this league. */
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
