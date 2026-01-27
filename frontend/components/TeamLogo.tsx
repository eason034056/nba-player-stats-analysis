/**
 * TeamLogo.tsx - NBA 球隊 Logo 元件
 * 
 * 顯示 NBA 球隊的官方 logo，自動根據球隊名稱取得對應的圖片
 * 
 * 功能：
 * - 自動載入 ESPN CDN 的高解析度 logo
 * - 支援自訂尺寸
 * - 提供載入失敗的後備方案
 * - 支援 Next.js Image 優化
 */

"use client";

import Image from "next/image";
import { getTeamLogo } from "@/lib/team-logos";
import { cn } from "@/lib/utils";

/**
 * TeamLogo Props
 * 
 * @property teamName - 球隊全名（必填）
 * @property size - Logo 尺寸，預設 24（px）
 * @property className - 額外的 CSS class
 * @property priority - 是否優先載入（用於 LCP 優化）
 */
interface TeamLogoProps {
  teamName: string;
  size?: number;
  className?: string;
  priority?: boolean;
}

/**
 * TeamLogo 元件
 * 
 * 根據球隊名稱顯示對應的 logo
 * 
 * @example
 * ```tsx
 * <TeamLogo teamName="Los Angeles Lakers" size={32} />
 * <TeamLogo teamName="Boston Celtics" size={48} className="rounded-full" />
 * ```
 */
export function TeamLogo({
  teamName,
  size = 24,
  className,
  priority = false,
}: TeamLogoProps) {
  const logoUrl = getTeamLogo(teamName);

  return (
    <div
      className={cn(
        "relative flex items-center justify-center shrink-0 bg-slate-800/30 rounded-lg overflow-hidden",
        className
      )}
      style={{ width: size, height: size }}
    >
      <Image
        src={logoUrl}
        alt={`${teamName} logo`}
        width={size}
        height={size}
        className="object-contain p-0.5"
        priority={priority}
        unoptimized // ESPN CDN 外部圖片，無需 Next.js 優化
      />
    </div>
  );
}

