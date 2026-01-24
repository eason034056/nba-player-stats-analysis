/**
 * about/page.tsx - 關於頁面
 * 
 * 包含：
 * - 網站說明
 * - 計算方法說明
 * - 免責聲明
 */

import { Calculator, AlertTriangle, BookOpen, ExternalLink } from "lucide-react";
import type { Metadata } from "next";

/**
 * 頁面 Metadata
 */
export const metadata: Metadata = {
  title: "關於",
  description: "了解去水機率計算的原理和免責聲明",
};

/**
 * 關於頁面元件
 */
export default function AboutPage() {
  return (
    <div className="container mx-auto px-4 py-8 page-enter max-w-4xl">
      {/* 頁面標題 */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gradient mb-2">
          關於 No-Vig NBA
        </h1>
        <p className="text-slate-400">
          了解去水機率計算的原理
        </p>
      </div>

      {/* 什麼是去水機率 */}
      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-4">
          <Calculator className="w-6 h-6 text-blue-400" />
          <h2 className="text-xl font-semibold text-slate-100">
            什麼是去水機率？
          </h2>
        </div>
        
        <div className="space-y-4 text-slate-300">
          <p>
            博彩公司的賠率包含「水錢」（Vig / Vigorish / Juice），
            這是博彩公司的利潤來源。因此，當你將 Over 和 Under 
            的賠率換算成隱含機率時，總和會超過 100%。
          </p>
          
          <div className="bg-slate-800/50 rounded-lg p-4">
            <p className="text-sm text-slate-400 mb-2">例如：</p>
            <ul className="space-y-2 text-sm">
              <li>
                <span className="text-amber-400">Over -110</span> → 
                隱含機率 = 110 / (110 + 100) = <span className="text-blue-400">52.38%</span>
              </li>
              <li>
                <span className="text-amber-400">Under -110</span> → 
                隱含機率 = 110 / (110 + 100) = <span className="text-blue-400">52.38%</span>
              </li>
              <li>
                總和 = 52.38% + 52.38% = <span className="text-red-400">104.76%</span>
                （超過 100%）
              </li>
              <li>
                水錢（Vig）= 104.76% - 100% = <span className="text-amber-400">4.76%</span>
              </li>
            </ul>
          </div>

          <p>
            「去水」就是將這些隱含機率正規化，使其總和等於 100%，
            從而得出更接近真實的公平機率。
          </p>

          <div className="bg-slate-800/50 rounded-lg p-4">
            <p className="text-sm text-slate-400 mb-2">去水計算：</p>
            <ul className="space-y-2 text-sm">
              <li>
                Over 公平機率 = 52.38% / 104.76% = <span className="text-green-400">50%</span>
              </li>
              <li>
                Under 公平機率 = 52.38% / 104.76% = <span className="text-green-400">50%</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* 計算方法 */}
      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-4">
          <BookOpen className="w-6 h-6 text-green-400" />
          <h2 className="text-xl font-semibold text-slate-100">
            計算方法
          </h2>
        </div>
        
        <div className="space-y-4 text-slate-300">
          <h3 className="font-medium text-slate-200">1. 美式賠率轉換</h3>
          <div className="bg-slate-800/50 rounded-lg p-4 font-mono text-sm">
            <p className="text-slate-400">若 odds &lt; 0 (如 -110):</p>
            <p className="text-blue-400 ml-4">p = |odds| / (|odds| + 100)</p>
            <p className="text-slate-400 mt-2">若 odds &gt; 0 (如 +150):</p>
            <p className="text-blue-400 ml-4">p = 100 / (odds + 100)</p>
          </div>

          <h3 className="font-medium text-slate-200">2. 去水公式</h3>
          <div className="bg-slate-800/50 rounded-lg p-4 font-mono text-sm">
            <p className="text-blue-400">p_fair = p_implied / (p_over + p_under)</p>
          </div>

          <h3 className="font-medium text-slate-200">3. 市場共識（平均法）</h3>
          <div className="bg-slate-800/50 rounded-lg p-4 font-mono text-sm">
            <p className="text-blue-400">consensus = mean(p_fair across bookmakers)</p>
          </div>
        </div>
      </section>

      {/* 免責聲明 */}
      <section className="card border-amber-800/50 bg-amber-900/10">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle className="w-6 h-6 text-amber-400" />
          <h2 className="text-xl font-semibold text-amber-300">
            免責聲明
          </h2>
        </div>
        
        <div className="space-y-3 text-slate-300">
          <p>
            <strong className="text-amber-300">⚠️ 本站為資訊與數據分析用途，不構成投注建議。</strong>
          </p>
          <ul className="list-disc list-inside space-y-2 text-slate-400">
            <li>本網站提供的資訊僅供參考和教育目的</li>
            <li>賠率和資料可能有延遲或缺漏，請以官方來源為準</li>
            <li>過去的數據不代表未來的結果</li>
            <li>請根據當地法律合法使用博彩服務</li>
            <li>如有賭博問題，請尋求專業協助</li>
          </ul>
        </div>
      </section>

      {/* 資料來源 */}
      <section className="card mt-6">
        <h2 className="text-lg font-semibold text-slate-200 mb-3">
          資料來源
        </h2>
        <p className="text-slate-400 text-sm">
          賠率資料由{" "}
          <a
            href="https://the-odds-api.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:text-blue-300 inline-flex items-center gap-1"
          >
            The Odds API
            <ExternalLink className="w-3 h-3" />
          </a>
          {" "}提供
        </p>
      </section>
    </div>
  );
}

