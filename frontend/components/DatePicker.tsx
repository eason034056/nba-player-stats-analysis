/**
 * DatePicker.tsx - 日期選擇器元件
 * 
 * 簡潔的日期選擇器
 * 使用原生 HTML input[type="date"]，再加上自訂樣式
 * 
 * 功能：
 * - 選擇日期
 * - 快捷按鈕（今天、明天）
 * - 前後日期導航
 */

"use client";

import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { format, addDays, subDays } from "date-fns";
import { zhTW } from "date-fns/locale";
import { cn, isToday as checkIsToday, isTomorrow as checkIsTomorrow } from "@/lib/utils";

/**
 * DatePicker Props
 * 
 * @property value - 當前日期（YYYY-MM-DD 格式）
 * @property onChange - 日期改變時的回調
 */
interface DatePickerProps {
  value: string;
  onChange: (date: string) => void;
}

/**
 * DatePicker 元件
 * 
 * 簡潔設計：左右箭頭 + 日期顯示 + 快捷按鈕
 */
export function DatePicker({ value, onChange }: DatePickerProps) {
  // 解析當前日期
  // 注意：直接用 new Date("YYYY-MM-DD") 會被當作 UTC 時間，可能導致時區問題
  // 改用 parse 函數來正確解析本地日期
  const currentDate = value ? new Date(value + "T00:00:00") : new Date();
  
  console.log('📆 DatePicker - value:', value, 'currentDate:', currentDate.toString());

  // 格式化日期為 YYYY-MM-DD
  const formatDateString = (date: Date) => format(date, "yyyy-MM-dd");

  // 格式化日期為友好顯示（M月d日 週X）
  const formatDisplayDate = (date: Date) => format(date, "M月d日 EEEE", { locale: zhTW });

  // 今天的日期
  const today = formatDateString(new Date());
  const tomorrow = formatDateString(addDays(new Date(), 1));

  // 導航到前一天
  const goToPreviousDay = () => {
    const prevDay = subDays(currentDate, 1);
    onChange(formatDateString(prevDay));
  };

  // 導航到後一天
  const goToNextDay = () => {
    const nextDay = addDays(currentDate, 1);
    onChange(formatDateString(nextDay));
  };

  // 判斷當前選擇
  const isToday = checkIsToday(value);
  const isTomorrow = checkIsTomorrow(value);

  return (
    <div className="flex items-center justify-center gap-4">
      {/* 左側：日期導航 */}
      <div className="flex items-center gap-1">
        {/* 前一天按鈕 */}
        <button
          type="button"
          onClick={goToPreviousDay}
          className="p-2.5 rounded-xl bg-slate-800/80 border border-slate-700/50 
                     text-slate-400 hover:text-white hover:bg-slate-700 hover:border-slate-600
                     transition-all duration-200 active:scale-95"
          title="前一天"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>

        {/* 日期顯示/選擇區 */}
        <div className="relative">
          <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800/80 border border-slate-700/50
                          min-w-[180px] justify-center cursor-pointer hover:border-slate-600 transition-colors">
            <Calendar className="w-4 h-4 text-amber-400" />
            <span className="text-slate-100 font-medium">
              {formatDisplayDate(currentDate)}
            </span>
          </div>
          {/* 隱藏的日期輸入框（覆蓋在上面） */}
          <input
            type="date"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="absolute inset-0 opacity-0 cursor-pointer w-full h-full"
          />
        </div>

        {/* 後一天按鈕 */}
        <button
          type="button"
          onClick={goToNextDay}
          className="p-2.5 rounded-xl bg-slate-800/80 border border-slate-700/50 
                     text-slate-400 hover:text-white hover:bg-slate-700 hover:border-slate-600
                     transition-all duration-200 active:scale-95"
          title="後一天"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>

      {/* 右側：快捷按鈕 */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onChange(today)}
          className={cn(
            "px-5 py-2.5 rounded-xl text-sm font-semibold",
            "transition-all duration-200 active:scale-95",
            isToday
              ? "bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-lg shadow-amber-500/25"
              : "bg-slate-800/80 border border-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-700"
          )}
        >
          今天
        </button>

        <button
          type="button"
          onClick={() => onChange(tomorrow)}
          className={cn(
            "px-5 py-2.5 rounded-xl text-sm font-semibold",
            "transition-all duration-200 active:scale-95",
            isTomorrow
              ? "bg-gradient-to-r from-amber-500 to-orange-500 text-white shadow-lg shadow-amber-500/25"
              : "bg-slate-800/80 border border-slate-700/50 text-slate-400 hover:text-white hover:bg-slate-700"
          )}
        >
          明天
        </button>
      </div>
    </div>
  );
}

