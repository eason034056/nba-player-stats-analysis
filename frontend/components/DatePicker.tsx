/**
 * DatePicker.tsx - Minimal Date Picker
 * 
 * Design Philosophy:
 * - Clean button design
 * - Black border style
 * - Red/yellow as selected state
 */

"use client";

import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { format, addDays, subDays } from "date-fns";
import { enUS } from "date-fns/locale";
import { cn, isToday as checkIsToday, isTomorrow as checkIsTomorrow } from "@/lib/utils";

interface DatePickerProps {
  value: string;
  onChange: (date: string) => void;
}

/**
 * DatePicker 元件
 * 
 * 極簡設計：清晰的按鈕、無裝飾
 */
export function DatePicker({ value, onChange }: DatePickerProps) {
  const currentDate = value ? new Date(value + "T00:00:00") : new Date();
  
  const formatDateString = (date: Date) => format(date, "yyyy-MM-dd");
  const formatDisplayDate = (date: Date) => format(date, "MMM d · EEE", { locale: enUS });

  const today = formatDateString(new Date());
  const tomorrow = formatDateString(addDays(new Date(), 1));

  const goToPreviousDay = () => {
    const prevDay = subDays(currentDate, 1);
    onChange(formatDateString(prevDay));
  };

  const goToNextDay = () => {
    const nextDay = addDays(currentDate, 1);
    onChange(formatDateString(nextDay));
  };

  const isToday = checkIsToday(value);
  const isTomorrow = checkIsTomorrow(value);

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-center lg:gap-6">
      {/* Date navigation */}
      <div className="flex items-center justify-center gap-3">
        {/* Previous day button */}
        <button
          type="button"
          onClick={goToPreviousDay}
          className="control-nav-button"
          title="Previous Day"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>

        {/* Date display/selection area */}
        <div className="relative">
          <div className="control-date-pill cursor-pointer">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-full border border-white/10 bg-white/6">
                <Calendar className="h-5 w-5 text-red" />
              </div>
              <div className="text-left">
                <p className="text-[11px] uppercase tracking-[0.26em] text-light">
                  Selected day
                </p>
                <span className="block text-lg font-semibold text-dark">
                  {formatDisplayDate(currentDate)}
                </span>
              </div>
            </div>
          </div>
          {/* Hidden date input */}
          <input
            type="date"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
          />
        </div>

        {/* Next day button */}
        <button
          type="button"
          onClick={goToNextDay}
          className="control-nav-button"
          title="Next Day"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>

      {/* Divider */}
      <div className="hidden h-10 w-px bg-white/10 lg:block" />

      {/* Quick buttons */}
      <div className="flex items-center justify-center gap-2">
        <button
          type="button"
          onClick={() => onChange(today)}
          className={cn(
            isToday ? "control-segment-active" : "control-segment"
          )}
        >
          Today
        </button>

        <button
          type="button"
          onClick={() => onChange(tomorrow)}
          className={cn(
            isTomorrow ? "control-segment-active" : "control-segment"
          )}
        >
          Tomorrow
        </button>
      </div>
    </div>
  );
}
