"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

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
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const dialog = dialogRef.current;
    const target = dialog?.querySelector<HTMLElement>(FOCUSABLE) ?? dialog;
    target?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      trigger?.focus();
    };
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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Filter games"
        tabIndex={-1}
        className="absolute inset-x-0 bottom-0 flex max-h-[82%] flex-col rounded-t-[24px] bg-white px-[18px] pb-[18px] pt-2.5 outline-none"
      >
        <div className="mx-auto mb-3 h-1 w-10 shrink-0 rounded-full bg-line-strong" />
        <div className="min-h-0 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}
