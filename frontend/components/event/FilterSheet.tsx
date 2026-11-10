"use client";

import { useEffect } from "react";

/**
 * Mobile filter sheet. The controls inside are the current game-log filters.
 * SPO-120c restyles those controls; this only moves them off the fourth tab.
 */
export function FilterSheet({
  open,
  onClose,
  children,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 md:hidden">
      <button
        type="button"
        aria-label="Close filters"
        className="absolute inset-0 bg-[rgba(29,21,48,0.36)]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-label="Filter games"
        className="absolute inset-x-0 bottom-0 flex max-h-[82%] flex-col rounded-t-[24px] bg-white px-[18px] pb-[18px] pt-2.5"
      >
        <div className="mx-auto mb-3 h-1 w-10 shrink-0 rounded-full bg-line-strong" />
        <div className="min-h-0 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
