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
    <div className="mx-auto max-w-5xl px-6 py-12 page-enter">
      <div className="grid gap-6 md:grid-cols-[1.2fr_0.8fr] mb-10">
        <div className="card">
          <div className="section-eyebrow">Methodology</div>
          <h1 className="hero-title mb-4">
            The pricing notes
            <span className="text-gradient block">behind the board.</span>
          </h1>
          <div className="accent-line mb-6" />
          <p className="text-lg leading-8 text-gray max-w-2xl">
            This product is built to turn messy market pricing into something more legible: what the book implies, how much vig sits inside the line, and what the fairer probability looks like after normalization.
          </p>
        </div>

        <div className="card">
          <p className="text-xs uppercase tracking-[0.22em] text-light mb-3">Why it matters</p>
          <div className="space-y-4 text-sm leading-7 text-gray">
            <p>Sportsbooks bake margin into the over/under pair, so raw implied probabilities usually add up to more than 100%.</p>
            <p>No-vig framing removes that margin so the market can be compared on a fairer baseline before you layer in history or projections.</p>
          </div>
        </div>
      </div>

      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center">
            <Calculator className="w-5 h-5 text-white" />
          </div>
          <h2 className="text-xl font-semibold text-dark">
            What is No-Vig Probability?
          </h2>
        </div>
        
        <div className="space-y-4 text-dark">
          <p>
            Bookmaker odds include &quot;vig&quot; (Vig / Vigorish / Juice),
            which is the bookmaker&apos;s profit margin. Therefore, when you convert
            Over and Under odds into implied probabilities, the sum exceeds 100%.
          </p>
          
          <div className="rounded-[24px] p-5 border border-white/8 bg-white/4">
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
            &quot;No-vig&quot; normalizes these implied probabilities so they sum to 100%,
            resulting in a fair probability estimate closer to reality.
          </p>

          <div className="rounded-[24px] p-5 border border-white/8 bg-white/4">
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

      <section className="card mb-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-full bg-dark flex items-center justify-center border border-white/10">
            <BookOpen className="w-5 h-5 text-cream" />
          </div>
          <h2 className="text-xl font-semibold text-dark">
            Calculation Method
          </h2>
        </div>
        
        <div className="space-y-6 text-dark">
          <div>
            <h3 className="font-semibold text-dark mb-3">1. American Odds Conversion</h3>
            <div className="bg-dark rounded-[24px] p-5 font-mono text-sm text-cream border border-white/8">
              <p className="text-gray-light">If odds &lt; 0 (e.g., -110):</p>
              <p className="text-yellow ml-4">p = |odds| / (|odds| + 100)</p>
              <p className="text-gray-light mt-3">If odds &gt; 0 (e.g., +150):</p>
              <p className="text-yellow ml-4">p = 100 / (odds + 100)</p>
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-dark mb-3">2. No-Vig Formula</h3>
            <div className="bg-dark rounded-[24px] p-5 font-mono text-sm border border-white/8">
              <p className="text-yellow">p_fair = p_implied / (p_over + p_under)</p>
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-dark mb-3">3. Market Consensus (Mean Method)</h3>
            <div className="bg-dark rounded-[24px] p-5 font-mono text-sm border border-white/8">
              <p className="text-yellow">consensus = mean(p_fair across bookmakers)</p>
            </div>
          </div>
        </div>
      </section>

      <section className="card border-red">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-full bg-red flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 text-white" />
          </div>
          <h2 className="text-xl font-semibold text-red">
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

      <section className="card mt-6">
        <h2 className="text-lg font-semibold text-dark mb-3">
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

      <div className="mt-16 text-center">
        <div className="divider-light mb-8" />
        <p className="text-sm text-gray">
          © 2024 No-Vig NBA. All rights reserved.
        </p>
      </div>
    </div>
  );
}
