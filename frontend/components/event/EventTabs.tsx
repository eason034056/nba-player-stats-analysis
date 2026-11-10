"use client";

import { EVENT_TABS, type EventTab } from "@/lib/event-page";
import { cn } from "@/lib/utils";

export function EventTabs({
  value,
  onChange,
  tabs = EVENT_TABS,
}: {
  value: EventTab;
  onChange: (tab: EventTab) => void;
  tabs?: ReadonlyArray<{ id: EventTab; label: string }>;
}) {
  return (
    <div className="sticky top-[66px] z-20 -mx-4 bg-canvas px-4 py-1.5 md:hidden">
      <div className="flex gap-0.5 rounded-xl bg-seg p-[3px]" role="tablist" aria-label="Event sections">
        {tabs.map((tab) => {
          const selected = tab.id === value;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onChange(tab.id)}
              className={cn(
                "min-h-[38px] flex-1 rounded-[9px] text-[13px] font-semibold",
                selected ? "bg-white text-brand" : "text-[#4A4458]",
              )}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
