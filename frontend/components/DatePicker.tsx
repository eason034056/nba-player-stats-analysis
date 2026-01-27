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
import { zhTW } from "date-fns/locale";
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
  const formatDisplayDate = (date: Date) => format(date, "MMM d, EEEE", { locale: zhTW });

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
    <div className="flex items-center justify-center gap-6">
      {/* Date navigation */}
      <div className="flex items-center gap-2">
        {/* Previous day button */}
        <button
          type="button"
          onClick={goToPreviousDay}
          className="w-10 h-10 rounded-lg flex items-center justify-center
                     border-2 border-dark text-dark
                     hover:bg-dark hover:text-cream
                     transition-all duration-150 active:scale-95"
          title="Previous Day"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>

        {/* Date display/selection area */}
        <div className="relative">
          <div className="flex items-center gap-3 px-5 py-2.5 rounded-lg
                          border-2 border-dark bg-white
                          min-w-[200px] justify-center cursor-pointer
                          hover:border-red transition-colors">
            <Calendar className="w-5 h-5 text-red" />
            <span className="font-bold text-dark">
              {formatDisplayDate(currentDate)}
            </span>
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
          className="w-10 h-10 rounded-lg flex items-center justify-center
                     border-2 border-dark text-dark
                     hover:bg-dark hover:text-cream
                     transition-all duration-150 active:scale-95"
          title="Next Day"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>

      {/* Divider */}
      <div className="w-px h-8 bg-dark/20" />

      {/* Quick buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(today)}
          className={cn(
            "px-5 py-2.5 rounded-lg text-sm font-bold",
            "border-2 transition-all duration-150 active:scale-95",
            isToday
              ? "bg-red border-red text-white"
              : "bg-white border-dark text-dark hover:bg-dark hover:text-cream"
          )}
        >
          Today
        </button>

        <button
          type="button"
          onClick={() => onChange(tomorrow)}
          className={cn(
            "px-5 py-2.5 rounded-lg text-sm font-bold",
            "border-2 transition-all duration-150 active:scale-95",
            isTomorrow
              ? "bg-yellow border-yellow text-dark"
              : "bg-white border-dark text-dark hover:bg-dark hover:text-cream"
          )}
        >
          Tomorrow
        </button>
      </div>
    </div>
  );
}
