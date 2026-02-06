/**
 * betslip/page.tsx - 下注列表頁面
 * 
 * 用戶管理已選擇的 picks，並生成分享圖片
 * 
 * 功能：
 * - 查看所有已添加的 picks
 * - 移除單個 pick 或清空所有
 * - 生成分享圖片（預覽、下載、複製到剪貼簿）
 * - 連結到詳細數據頁面
 * 
 * 路由：/betslip
 */

"use client";

import { useState, useRef, useCallback } from "react";
import Link from "next/link";
import { 
  ClipboardList, 
  Trash2, 
  X, 
  ExternalLink,
  Download,
  Copy,
  Image as ImageIcon,
  Check,
  Flame,
  TrendingUp,
  Share2
} from "lucide-react";
import { useBetSlip, type BetSlipPick } from "@/contexts/BetSlipContext";
import { TeamLogo } from "@/components/TeamLogo";
import { METRIC_DISPLAY_NAMES, DIRECTION_DISPLAY_NAMES } from "@/lib/schemas";
import { formatProbability } from "@/lib/utils";

// ==================== 輔助函數 ====================

const SHARE_FONT_SANS = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif";
const SHARE_FONT_MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace";

/**
 * metric → market 轉換
 */
function metricToMarket(metric: string): string {
  switch (metric) {
    case "points": return "player_points";
    case "rebounds": return "player_rebounds";
    case "assists": return "player_assists";
    case "pra": return "player_points_rebounds_assists";
    default: return "player_points";
  }
}

/**
 * 機率等級判斷
 */
function getProbabilityLevel(probability: number): "high" | "medium" {
  return probability >= 0.70 ? "high" : "medium";
}

/**
 * 格式化比賽時間
 */
function formatGameTime(isoString: string): string {
  const date = new Date(isoString);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

// ==================== 子組件 ====================

/**
 * 單一 Pick 卡片（列表版本）
 */
function BetSlipCard({ pick, onRemove }: { pick: BetSlipPick; onRemove: () => void }) {
  const level = getProbabilityLevel(pick.probability);
  const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
  const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
  
  const marketKey = metricToMarket(pick.metric);
  const detailHref = `/event/${pick.event_id}?player=${encodeURIComponent(pick.player_name)}&market=${marketKey}&threshold=${pick.threshold}`;

  return (
    <div className="card group animate-fade-in">
      <div className="flex items-start gap-4">
        {/* 球隊 Logo */}
        <TeamLogo 
          teamName={pick.player_team || pick.home_team} 
          size={48} 
          className="shrink-0"
        />
        
        {/* 主要內容 */}
        <div className="flex-1 min-w-0">
          {/* 球員名稱和移除按鈕 */}
          <div className="flex items-start justify-between mb-2">
            <div>
              <h3 className="text-lg font-bold text-dark">
                {pick.player_name}
              </h3>
              <p className="text-sm text-gray">
                {pick.player_team && (
                  <span className="font-medium">{pick.player_team} · </span>
                )}
                {pick.away_team} @ {pick.home_team}
              </p>
            </div>
            
            {/* 移除按鈕 */}
            <button
              onClick={onRemove}
              className="p-2 rounded-lg text-gray hover:text-red hover:bg-red/10 transition-colors"
              title="Remove from bet slip"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          
          {/* 預測內容 */}
          <div className="flex items-center justify-between mb-3">
            <div className={`
              px-3 py-1.5 rounded-lg text-sm font-bold
              ${pick.direction === "over"
                ? "bg-green-500/10 text-green-600 border border-green-500/30"
                : "bg-blue-500/10 text-blue-600 border border-blue-500/30"
              }
            `}>
              {metricName} {directionName} {pick.threshold}
            </div>
            
            {/* 機率顯示 */}
            <div className="flex items-center gap-2">
              {level === "high" && (
                <Flame className="w-4 h-4 text-green-500" />
              )}
              <span className={`
                text-2xl font-mono font-bold
                ${level === "high" ? "text-green-500" : "text-yellow"}
              `}>
                {formatProbability(pick.probability)}
              </span>
            </div>
          </div>
          
          {/* 比賽時間和查看詳情 */}
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray">
              {formatGameTime(pick.commence_time)}
            </span>
            <Link
              href={detailHref}
              className="flex items-center gap-1 text-red hover:underline font-medium"
            >
              <span>View Details</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 空狀態
 */
function EmptyState() {
  return (
    <div className="card text-center py-16">
      <div className="w-20 h-20 mx-auto mb-6 rounded-full border-2 border-dark/20 flex items-center justify-center">
        <ClipboardList className="w-10 h-10 text-gray" />
      </div>
      <h3 className="text-2xl font-bold text-dark mb-3">
        Your Bet Slip is Empty
      </h3>
      <p className="text-gray mb-8 max-w-md mx-auto">
        Right-click on any pick in the Daily Picks page to add it to your bet slip.
      </p>
      <Link
        href="/picks"
        className="btn-primary inline-flex items-center gap-2"
      >
        <TrendingUp className="w-4 h-4" />
        Browse Daily Picks
      </Link>
    </div>
  );
}

/**
 * 分享圖片組件（用於生成圖片）
 * 
 * 這個組件會被 html2canvas 截圖
 * 使用固定尺寸和內聯樣式確保一致性
 * 風格與網頁保持一致：米色背景、白色卡片、紅色品牌色
 */
function ShareImageTemplate({ 
  picks, 
  forwardedRef 
}: { 
  picks: BetSlipPick[];
  forwardedRef: React.RefObject<HTMLDivElement>;
}) {
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  return (
    <div
      ref={forwardedRef}
      style={{
        width: 600,
        padding: 32,
        background: "#FFF2DF", // 米色背景，與網頁一致
        fontFamily: SHARE_FONT_SANS,
        fontSize: 16,
        boxSizing: "border-box",
        fontSynthesis: "none",
        textRendering: "geometricPrecision",
      }}
    >
      {/* Header - 紅色標題區 */}
      <div style={{ 
        marginBottom: 24, 
        padding: 20,
        background: "#E92016", // 紅色品牌色
        borderRadius: 12,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: 8,
            background: "#FFF2DF",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}>
            <span style={{ fontSize: 24, lineHeight: "24px" }}>🏀</span>
          </div>
          <div style={{ 
            fontSize: 24, 
            fontWeight: 800, 
            color: "#FFF2DF",
            margin: 0,
            lineHeight: 1.15,
          }}>
            My NBA Picks
          </div>
        </div>
        <div style={{ 
          fontSize: 14, 
          color: "rgba(255,242,223,0.8)",
          margin: 0,
          marginLeft: 52,
          lineHeight: 1.35,
        }}>
          {today}
        </div>
      </div>

      {/* Picks List */}
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {picks.map((pick) => {
          const level = getProbabilityLevel(pick.probability);
          const metricName = METRIC_DISPLAY_NAMES[pick.metric] || pick.metric;
          const directionName = DIRECTION_DISPLAY_NAMES[pick.direction] || pick.direction;
          
          return (
            <div
              key={pick.id}
              style={{
                background: "#FFFFFF",
                borderRadius: 12,
                padding: 16,
                border: "2px solid #1a1a1a",
                position: "relative" as const,
              }}
            >
              {/* HOT 標籤 */}
              {level === "high" && (
                <div style={{
                  position: "absolute" as const,
                  top: 12,
                  right: 12,
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "4px 10px",
                  borderRadius: 999,
                  background: "#22c55e",
                  color: "#fff",
                  fontSize: 11,
                  fontWeight: 700,
                  lineHeight: 1,
                }}>
                  🔥 HOT
                </div>
              )}
              
              {/* 球員資訊 */}
              <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12 }}>
                <div style={{ flex: 1, paddingRight: level === "high" ? 70 : 0 }}>
                  <div style={{ 
                    fontSize: 18, 
                    fontWeight: 700, 
                    color: "#1a1a1a",
                    margin: 0,
                    marginBottom: 4,
                    lineHeight: 1.2,
                  }}>
                    {pick.player_name}
                  </div>
                  <div style={{ 
                    fontSize: 13, 
                    color: "#666",
                    margin: 0,
                    lineHeight: 1.35,
                  }}>
                    {pick.player_team && <span style={{ fontWeight: 500 }}>{pick.player_team} · </span>}
                    {pick.away_team} @ {pick.home_team}
                  </div>
                </div>
              </div>
              
              {/* 預測內容和機率 - 使用 flex 對齊 */}
              <div style={{ 
                display: "flex", 
                alignItems: "center", 
                justifyContent: "space-between",
              }}>
                {/* 預測標籤 */}
                <div style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  padding: "8px 16px",
                  borderRadius: 8,
                  fontSize: 14,
                  fontWeight: 700,
                  lineHeight: 1.2,
                  background: pick.direction === "over" ? "rgba(34, 197, 94, 0.1)" : "rgba(59, 130, 246, 0.1)",
                  color: pick.direction === "over" ? "#16a34a" : "#2563eb",
                  border: pick.direction === "over" ? "2px solid rgba(34, 197, 94, 0.3)" : "2px solid rgba(59, 130, 246, 0.3)",
                }}>
                  {metricName} {directionName} {pick.threshold}
                </div>
                
                {/* 機率數字 - 固定寬度確保對齊 */}
                <div style={{
                  fontSize: 32,
                  fontWeight: 700,
                  fontFamily: SHARE_FONT_MONO,
                  color: level === "high" ? "#22c55e" : "#eab308",
                  minWidth: 100,
                  textAlign: "right" as const,
                  lineHeight: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                }}>
                  {formatProbability(pick.probability)}
                </div>
              </div>
              
              {/* 機率進度條 */}
              <div style={{
                marginTop: 12,
                height: 6,
                background: "rgba(0,0,0,0.1)",
                borderRadius: 999,
                overflow: "hidden",
              }}>
                <div style={{
                  height: "100%",
                  width: `${pick.probability * 100}%`,
                  background: level === "high" ? "#22c55e" : "#eab308",
                  borderRadius: 999,
                }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div style={{ 
        marginTop: 24, 
        paddingTop: 16, 
        borderTop: "2px solid rgba(0,0,0,0.1)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}>
        <div style={{ 
          fontSize: 13, 
          color: "#666",
          margin: 0,
          fontWeight: 500,
          lineHeight: 1.35,
        }}>
          Generated by No-Vig NBA
        </div>
        <div style={{ 
          fontSize: 13, 
          color: "#666",
          margin: 0,
          fontWeight: 600,
          lineHeight: 1.35,
        }}>
          {picks.length} pick{picks.length !== 1 ? "s" : ""}
        </div>
      </div>
    </div>
  );
}

// ==================== 主頁面組件 ====================

/**
 * BetSlipPage - 下注列表頁面主組件
 */
export default function BetSlipPage() {
  const { picks, removePick, clearAll, count } = useBetSlip();
  const [showPreview, setShowPreview] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [copySuccess, setCopySuccess] = useState(false);
  const shareImageRef = useRef<HTMLDivElement>(null);

  /**
   * 生成圖片的核心函數
   * 
   * 使用 html-to-image 的 toCanvas，它透過 SVG foreignObject
   * 借用瀏覽器原生渲染引擎，CSS 保真度遠高於 html2canvas。
   * 不需要 clone + tempContainer 的 hack。
   */
  const generateCanvas = useCallback(async () => {
    if (!shareImageRef.current || picks.length === 0) return null;
    
    const { toCanvas } = await import("html-to-image");
    const element = shareImageRef.current;

    // 等待字體載入，避免 fallback 字體造成高度偏差
    if ("fonts" in document) {
      await document.fonts.ready;
    }

    // html-to-image 的 toCanvas 直接使用瀏覽器渲染
    // pixelRatio: 2 確保 Retina 品質
    const rawCanvas = await toCanvas(element, {
      pixelRatio: 2,
      backgroundColor: "#FFF2DF",
      // 過濾掉不需要的隱藏元素標記
      filter: (node: HTMLElement) => {
        // 排除 aria-hidden 以外的所有節點（保留模板本身）
        return true;
      },
    });

    // 將透明像素強制鋪上背景色，避免下載 PNG 出現透明背景
    const canvas = document.createElement("canvas");
    canvas.width = rawCanvas.width;
    canvas.height = rawCanvas.height;

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return rawCanvas;
    }

    ctx.fillStyle = "#FFF2DF";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(rawCanvas, 0, 0);

    return canvas;
  }, [picks]);

  /**
   * 生成圖片並下載
   */
  const handleDownload = useCallback(async () => {
    if (picks.length === 0) return;
    
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      
      // 創建下載連結（加入時間戳避免快取）
      const url = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = url;
      const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
      link.download = `nba-picks-${timestamp}.png`;
      link.click();
      console.log("Downloaded new image:", timestamp);
    } catch (error) {
      console.error("Failed to generate image:", error);
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas]);

  /**
   * 複製圖片到剪貼簿
   */
  const handleCopyToClipboard = useCallback(async () => {
    if (picks.length === 0) return;
    
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      
      // 轉換為 Blob
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      
      // 複製到剪貼簿
      await navigator.clipboard.write([
        new ClipboardItem({ "image/png": blob })
      ]);
      
      setCopySuccess(true);
      setTimeout(() => setCopySuccess(false), 2000);
    } catch (error) {
      console.error("Failed to copy image:", error);
      // 某些瀏覽器可能不支援 ClipboardItem
      alert("Your browser may not support copying images. Please try downloading instead.");
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas]);

  /**
   * 使用 Web Share API 分享（行動裝置）
   */
  const handleShare = useCallback(async () => {
    if (picks.length === 0) return;
    
    // 檢查是否支援 Web Share API
    if (!navigator.share) {
      // 降級為下載
      handleDownload();
      return;
    }
    
    setIsGenerating(true);
    try {
      const canvas = await generateCanvas();
      if (!canvas) return;
      
      const blob = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((blob) => {
          if (blob) resolve(blob);
          else reject(new Error("Failed to create blob"));
        }, "image/png");
      });
      
      const file = new File([blob], "nba-picks.png", { type: "image/png" });
      
      await navigator.share({
        files: [file],
        title: "My NBA Picks",
        text: `Check out my ${picks.length} NBA pick${picks.length !== 1 ? "s" : ""} for today!`,
      });
    } catch (error) {
      // 用戶取消分享不算錯誤
      if ((error as Error).name !== "AbortError") {
        console.error("Failed to share:", error);
      }
    } finally {
      setIsGenerating(false);
    }
  }, [picks, generateCanvas, handleDownload]);

  return (
    <div className="min-h-screen page-enter">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* 頁面標題 */}
        <div className="text-center mb-12">
          <div className="inline-block mb-6">
            <span className="badge-danger">
              <ClipboardList className="w-3.5 h-3.5 mr-1.5" />
              My Selections
            </span>
          </div>
          
          <h1 className="hero-title mb-4">
            Bet <span className="text-red">Slip</span>
          </h1>
          
          <div className="accent-line mx-auto mb-6" />
          
          <p className="text-lg text-gray max-w-lg mx-auto">
            Manage your selected picks and generate shareable images for your friends
          </p>
        </div>

        {/* 空狀態 */}
        {count === 0 && <EmptyState />}

        {/* 有 picks 時顯示內容 */}
        {count > 0 && (
          <>
            {/* 操作按鈕區 */}
            <div className="flex items-center justify-between mb-8">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-bold text-dark">
                  Your Picks
                </h2>
                <span className="badge-neutral">
                  {count} {count === 1 ? "pick" : "picks"}
                </span>
              </div>
              
              <div className="flex items-center gap-3">
                {/* 預覽按鈕 */}
                <button
                  onClick={() => setShowPreview(!showPreview)}
                  className="btn-refresh"
                >
                  <ImageIcon className="w-4 h-4" />
                  <span>{showPreview ? "Hide Preview" : "Preview Image"}</span>
                </button>
                
                {/* 清空按鈕 */}
                <button
                  onClick={clearAll}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-bold text-red hover:bg-red/10 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Clear All</span>
                </button>
              </div>
            </div>

            {/* Picks 列表 */}
            <div className="grid grid-cols-1 gap-4 mb-8">
              {picks.map((pick) => (
                <BetSlipCard
                  key={pick.id}
                  pick={pick}
                  onRemove={() => removePick(pick.id)}
                />
              ))}
            </div>

            {/* 分享圖片預覽 */}
            {showPreview && (
              <div className="mb-8">
                <h3 className="text-lg font-bold text-dark mb-4">Share Image Preview</h3>
                <div className="overflow-x-auto pb-4">
                  <div className="inline-block rounded-xl overflow-hidden shadow-lg">
                    <ShareImageTemplate picks={picks} forwardedRef={shareImageRef} />
                  </div>
                </div>
              </div>
            )}

            {/* 隱藏的分享圖片模板（用於生成圖片）
                在生成圖片時會暫時將 opacity 設為 1 來確保正確渲染 */}
            {!showPreview && (
              <div 
                style={{
                  position: "fixed",
                  left: 0,
                  top: 0,
                  opacity: 0,
                  pointerEvents: "none",
                  zIndex: -1,
                }}
                aria-hidden="true"
              >
                <ShareImageTemplate picks={picks} forwardedRef={shareImageRef} />
              </div>
            )}

            {/* 分享操作按鈕 */}
            <div className="card">
              <h3 className="text-lg font-bold text-dark mb-4">Share Your Picks</h3>
              <p className="text-gray text-sm mb-6">
                Generate an image of your picks to share with friends on social media or messaging apps.
              </p>
              
              <div className="flex flex-wrap gap-3">
                {/* 下載按鈕 */}
                <button
                  onClick={handleDownload}
                  disabled={isGenerating}
                  className="btn-primary flex items-center gap-2"
                >
                  <Download className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`} />
                  <span>{isGenerating ? "Generating..." : "Download PNG"}</span>
                </button>
                
                {/* 複製到剪貼簿 */}
                <button
                  onClick={handleCopyToClipboard}
                  disabled={isGenerating}
                  className="btn-refresh flex items-center gap-2"
                >
                  {copySuccess ? (
                    <>
                      <Check className="w-4 h-4 text-green-500" />
                      <span className="text-green-500">Copied!</span>
                    </>
                  ) : (
                    <>
                      <Copy className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`} />
                      <span>Copy to Clipboard</span>
                    </>
                  )}
                </button>
                
                {/* 分享按鈕（使用 Web Share API） */}
                <button
                  onClick={handleShare}
                  disabled={isGenerating}
                  className="btn-refresh flex items-center gap-2"
                >
                  <Share2 className={`w-4 h-4 ${isGenerating ? "animate-pulse" : ""}`} />
                  <span>Share</span>
                </button>
              </div>
            </div>
          </>
        )}

        {/* 底部提示 */}
        <div className="mt-16 text-center">
          <div className="divider-light mb-8" />
          <p className="text-sm text-gray max-w-lg mx-auto">
            Right-click on any pick in the Daily Picks page to quickly add or remove it from your bet slip.
            Your selections are saved locally and will persist even after refreshing the page.
          </p>
        </div>
      </div>
    </div>
  );
}
