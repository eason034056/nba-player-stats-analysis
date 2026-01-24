/**
 * event/[eventId]/page.tsx - 賽事詳情 / 計算頁面
 * 
 * 這是整個應用的核心頁面！
 * 
 * 功能：
 * - 顯示比賽資訊
 * - 選擇統計類型（Points/Assists/Rebounds/PRA）
 * - 輸入球員名稱（帶 Autocomplete）或從列表點擊選擇
 * - 選擇博彩公司
 * - 計算並顯示去水機率
 * - 顯示球員歷史數據分析（含 Histogram 視覺化）
 */

"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  Calculator,
  Loader2,
  AlertCircle,
  Calendar,
} from "lucide-react";
import { getEvents, calculateNoVig } from "@/lib/api";
import {
  calculatorFormSchema,
  type CalculatorFormData,
  type NoVigResponse,
} from "@/lib/schemas";
import { formatFullDate } from "@/lib/utils";
import { PlayerInput } from "@/components/PlayerInput";
import { BookmakerSelect } from "@/components/BookmakerSelect";
import { MarketSelect, type MarketKey } from "@/components/MarketSelect";
import { ResultsTable } from "@/components/ResultsTable";
import { PlayerHistoryStats } from "@/components/PlayerHistoryStats";

/**
 * 賽事詳情頁元件
 * 
 * 路由參數：eventId - 賽事 ID
 */
export default function EventPage() {
  // 從 URL 取得 eventId 參數
  // useParams: Next.js 的 hook，用於取得動態路由參數
  const params = useParams();
  const eventId = params.eventId as string;

  // 路由器，用於返回上一頁
  const router = useRouter();

  // 計算結果狀態
  const [result, setResult] = useState<NoVigResponse | null>(null);

  // 市場類型狀態（獨立管理，因為不在表單驗證中）
  const [selectedMarket, setSelectedMarket] = useState<MarketKey>("player_points");

  // 表單設定
  // useForm: react-hook-form 的核心 hook
  // - 管理表單狀態
  // - 處理表單驗證
  // - 處理表單提交
  const {
    control,       // 用於 Controller 元件
    handleSubmit,  // 表單提交處理器
    watch,         // 監聽表單值
    setValue,      // 設定表單值
    formState: { errors },  // 表單錯誤
  } = useForm<CalculatorFormData>({
    // zodResolver: 使用 Zod schema 進行驗證
    resolver: zodResolver(calculatorFormSchema),
    // 預設值
    defaultValues: {
      player_name: "",
      bookmakers: [],  // 空陣列表示全選
    },
  });

  // 監聽表單值（用於顯示）
  const playerName = watch("player_name");

  // 取得賽事資訊（用於顯示比賽詳情）
  // 這裡重用 events 查詢，從中找出對應的賽事
  const { data: eventsData, isLoading: isEventsLoading } = useQuery({
    queryKey: ["events", "all"],
    queryFn: () => getEvents(),
    staleTime: 5 * 60 * 1000, // 5 分鐘
  });

  // 從賽事列表中找出當前賽事
  const currentEvent = eventsData?.events.find(
    (e) => e.event_id === eventId
  );

  // 計算去水機率 mutation
  // useMutation: 用於會改變伺服器狀態的操作
  // 與 useQuery 不同，mutation 需要手動觸發
  const mutation = useMutation({
    mutationFn: calculateNoVig,
    onSuccess: (data) => {
      // 成功時設定結果
      setResult(data);
    },
    onError: (error) => {
      console.error("計算失敗:", error);
    },
  });

  // 處理市場類型變更
  // 當市場類型改變時，清除之前的結果和選擇的球員
  const handleMarketChange = (market: MarketKey) => {
    setSelectedMarket(market);
    setResult(null);
    setValue("player_name", ""); // 清除已選擇的球員
  };

  // 表單提交處理
  const onSubmit = (data: CalculatorFormData) => {
    // 清除之前的結果
    setResult(null);

    // 發送計算請求
    mutation.mutate({
      event_id: eventId,
      player_name: data.player_name,
      market: selectedMarket, // 使用選擇的市場類型
      regions: "us",
      bookmakers: data.bookmakers.length > 0 ? data.bookmakers : null,
      odds_format: "american",
    });
  };

  return (
    <div className="container mx-auto px-4 py-8 page-enter">
      {/* 返回按鈕 */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-2 text-slate-400 hover:text-slate-200 
                   transition-colors duration-200 mb-6"
      >
        <ArrowLeft className="w-5 h-5" />
        <span>返回賽事列表</span>
      </button>

      {/* 比賽資訊卡片 */}
      <div className="card mb-8">
        {isEventsLoading ? (
          // 載入中骨架屏
          <div className="animate-pulse">
            <div className="skeleton h-8 w-64 mb-4" />
            <div className="skeleton h-4 w-48" />
          </div>
        ) : currentEvent ? (
          // 顯示比賽資訊
          <>
            <div className="flex items-center gap-3 mb-4">
              <span className="text-3xl">🏀</span>
              <h1 className="text-2xl font-bold text-slate-100">
                {currentEvent.away_team} @ {currentEvent.home_team}
              </h1>
            </div>
            <div className="flex items-center gap-2 text-slate-400">
              <Calendar className="w-4 h-4" />
              <span>{formatFullDate(currentEvent.commence_time)}</span>
            </div>
          </>
        ) : (
          // 找不到比賽
          <div className="flex items-center gap-3 text-amber-400">
            <AlertCircle className="w-6 h-6" />
            <span>找不到此比賽的資訊</span>
          </div>
        )}
      </div>

      {/* 計算表單 */}
      <form onSubmit={handleSubmit(onSubmit)}>
        {/* 市場類型選擇 */}
        <div className="card mb-6">
          <MarketSelect
            value={selectedMarket}
            onChange={handleMarketChange}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          {/* 球員輸入（帶有搜尋和列表） */}
          <div className="card">
            <Controller
              name="player_name"
              control={control}
              render={({ field }) => (
                <PlayerInput
                  eventId={eventId}
                  market={selectedMarket}
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
            {/* 錯誤訊息 */}
            {errors.player_name && (
              <p className="mt-2 text-sm text-red-400">
                {errors.player_name.message}
              </p>
            )}
          </div>

          {/* 博彩公司選擇 */}
          <div className="card">
            <Controller
              name="bookmakers"
              control={control}
              render={({ field }) => (
                <BookmakerSelect
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
          </div>
        </div>

        {/* 計算按鈕 */}
        <div className="flex justify-center">
          <button
            type="submit"
            disabled={mutation.isPending || !playerName}
            className="btn-primary flex items-center gap-2 px-8 py-3 text-lg
                       disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                <span>計算中...</span>
              </>
            ) : (
              <>
                <Calculator className="w-5 h-5" />
                <span>計算去水機率</span>
              </>
            )}
          </button>
        </div>
      </form>

      {/* 錯誤提示 */}
      {mutation.isError && (
        <div className="card mt-6 border-red-800/50 bg-red-900/10">
          <div className="flex items-start gap-3">
            <AlertCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
            <div>
              <h3 className="font-semibold text-red-300 mb-1">計算失敗</h3>
              <p className="text-slate-400 text-sm">
                {mutation.error instanceof Error
                  ? mutation.error.message
                  : "無法計算去水機率，請稍後再試"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* 計算結果 */}
      <div className="mt-8">
        <ResultsTable
          data={result}
          isLoading={mutation.isPending}
        />
      </div>

      {/* 說明 */}
      {!result && !mutation.isPending && (
        <div className="mt-8 p-4 bg-slate-900/30 rounded-lg border border-slate-800/50">
          <h3 className="text-sm font-medium text-slate-400 mb-2">
            📊 什麼是去水機率？
          </h3>
          <p className="text-sm text-slate-500 leading-relaxed">
            博彩公司的賠率包含「水錢」（vig/juice），使得 Over 和 Under 
            的隱含機率總和超過 100%。去水機率是將這些隱含機率正規化後，
            得出更接近真實的公平機率估計。水錢越低的博彩公司，
            其賠率越接近真實機率。
          </p>
        </div>
      )}

      {/* ==================== 歷史數據分析區域 ==================== */}
      <div className="mt-12 pt-8 border-t border-slate-800/50">
        <div className="card">
          <PlayerHistoryStats
            initialPlayer={playerName}
            initialMarket={selectedMarket}
            onPlayerSelect={(name) => setValue("player_name", name)}
          />
        </div>
      </div>
    </div>
  );
}
