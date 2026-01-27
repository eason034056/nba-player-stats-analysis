/**
 * about/page.tsx - Minimal About Page
 * 
 * Design Philosophy:
 * - Clear information hierarchy
 * - White cards with black borders
 * - Red for important warnings
 */

import { Calculator, AlertTriangle, BookOpen, ExternalLink } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "About",
  description: "Learn about the principles of no-vig probability calculation and disclaimer",
};

export default function AboutPage() {
  return (
    <div className="max-w-4xl mx-auto px-6 py-12 page-enter">
      {/* Page title */}
      <div className="text-center mb-16">
        <h1 className="hero-title mb-4">
          About <span className="text-red">No-Vig</span>
        </h1>
        <div className="accent-line mx-auto mb-6" />
        <p className="text-lg text-gray">
          Learn about the principles of no-vig probability calculation
        </p>
      </div>

      {/* What is no-vig probability */}
      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center">
            <Calculator className="w-5 h-5 text-white" />
          </div>
          <h2 className="text-xl font-bold text-dark">
            What is No-Vig Probability?
          </h2>
        </div>
        
        <div className="space-y-4 text-dark">
          <p>
            Bookmaker odds include "vig" (Vig / Vigorish / Juice),
            which is the bookmaker's profit margin. Therefore, when you convert
            Over and Under odds into implied probabilities, the sum exceeds 100%.
          </p>
          
          <div className="bg-cream rounded-lg p-5 border-2 border-dark/10">
            <p className="text-sm text-gray font-medium mb-3">Example:</p>
            <ul className="space-y-2 text-sm">
              <li>
                <span className="font-bold">Over -110</span> → 
                Implied probability = 110 / (110 + 100) = <span className="text-red font-bold">52.38%</span>
              </li>
              <li>
                <span className="font-bold">Under -110</span> → 
                Implied probability = 110 / (110 + 100) = <span className="text-red font-bold">52.38%</span>
              </li>
              <li>
                Sum = 52.38% + 52.38% = <span className="text-red font-bold">104.76%</span>
                (exceeds 100%)
              </li>
              <li>
                Vig = 104.76% - 100% = <span className="font-bold highlight">4.76%</span>
              </li>
            </ul>
          </div>

          <p>
            "No-vig" normalizes these implied probabilities so they sum to 100%,
            resulting in a fair probability estimate closer to reality.
          </p>

          <div className="bg-cream rounded-lg p-5 border-2 border-dark/10">
            <p className="text-sm text-gray font-medium mb-3">No-vig calculation:</p>
            <ul className="space-y-2 text-sm">
              <li>
                Over fair probability = 52.38% / 104.76% = <span className="text-green-600 font-bold">50%</span>
              </li>
              <li>
                Under fair probability = 52.38% / 104.76% = <span className="text-green-600 font-bold">50%</span>
              </li>
            </ul>
          </div>
        </div>
      </section>

      {/* Calculation method */}
      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-dark flex items-center justify-center">
            <BookOpen className="w-5 h-5 text-cream" />
          </div>
          <h2 className="text-xl font-bold text-dark">
            Calculation Method
          </h2>
        </div>
        
        <div className="space-y-6 text-dark">
          <div>
            <h3 className="font-bold text-dark mb-3">1. American Odds Conversion</h3>
            <div className="bg-dark rounded-lg p-5 font-mono text-sm text-cream">
              <p className="text-gray-light">If odds &lt; 0 (e.g., -110):</p>
              <p className="text-yellow ml-4">p = |odds| / (|odds| + 100)</p>
              <p className="text-gray-light mt-3">If odds &gt; 0 (e.g., +150):</p>
              <p className="text-yellow ml-4">p = 100 / (odds + 100)</p>
            </div>
          </div>

          <div>
            <h3 className="font-bold text-dark mb-3">2. No-Vig Formula</h3>
            <div className="bg-dark rounded-lg p-5 font-mono text-sm">
              <p className="text-yellow">p_fair = p_implied / (p_over + p_under)</p>
            </div>
          </div>

          <div>
            <h3 className="font-bold text-dark mb-3">3. Market Consensus (Mean Method)</h3>
            <div className="bg-dark rounded-lg p-5 font-mono text-sm">
              <p className="text-yellow">consensus = mean(p_fair across bookmakers)</p>
            </div>
          </div>
        </div>
      </section>

      {/* Disclaimer */}
      <section className="card border-red">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-red flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 text-white" />
          </div>
          <h2 className="text-xl font-bold text-red">
            Disclaimer
          </h2>
        </div>
        
        <div className="space-y-4">
          <p className="font-bold text-red text-lg">
            ⚠️ This site is for informational and data analysis purposes only and does not constitute betting advice.
          </p>
          <ul className="list-disc list-inside space-y-2 text-gray">
            <li>The information provided on this website is for reference and educational purposes only</li>
            <li>Odds and data may be delayed or incomplete, please refer to official sources</li>
            <li>Past data does not represent future results</li>
            <li>Please use betting services legally according to local laws</li>
            <li>If you have gambling problems, please seek professional help</li>
          </ul>
        </div>
      </section>

      {/* Data source */}
      <section className="card mt-6">
        <h2 className="text-lg font-bold text-dark mb-3">
          Data Source
        </h2>
        <p className="text-gray">
          Odds data provided by{" "}
          <a
            href="https://the-odds-api.com"
            target="_blank"
            rel="noopener noreferrer"
            className="text-red font-bold hover:underline inline-flex items-center gap-1"
          >
            The Odds API
            <ExternalLink className="w-3 h-3" />
          </a>
        </p>
      </section>

      {/* 底部裝飾 */}
      <div className="mt-16 text-center">
        <div className="divider-light mb-8" />
        <p className="text-sm text-gray">
          © 2024 No-Vig NBA. All rights reserved.
        </p>
      </div>
    </div>
  );
}
