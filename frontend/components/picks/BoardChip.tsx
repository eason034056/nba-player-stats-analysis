"use client";

import { cn } from "@/lib/utils";

export function BoardChip({
  active,
  onClick,
  children,
  mono = false,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
  mono?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "min-h-[38px] shrink-0 whitespace-nowrap rounded-full border px-3.5 py-2",
        mono ? "font-mono text-xs font-bold" : "text-[13px] font-semibold",
        active ? "border-brand bg-brand text-white" : "border-muted bg-white text-ink",
      )}
    >
      {children}
    </button>
  );
}
