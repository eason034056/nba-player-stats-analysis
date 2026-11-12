/**
 * /about — Method, shared by NBA and WNBA.
 *
 * The layout follows the November 2026 prototype. The copy describes
 * the calculations the app actually runs. A five-signal blend and
 * signal verdicts are marked planned because the API does not return them.
 */

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Method",
  description:
    "How No-Vig reads a prop: remove the bookmaker margin, then show the historical hit rate and any projection the API returns.",
};

export default function AboutPage() {
  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-[22px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-[32px] font-bold leading-none tracking-[-0.035em] md:text-[52px]">
          How we read a prop
        </h1>
        <p className="max-w-[720px] text-base leading-relaxed text-muted">
          The price and the player&apos;s history are separate reads. The bookmaker margin
          comes out of the posted odds. The board then shows how often the player cleared
          that line, plus a projection when the API returns one. Those numbers are not
          blended into a single probability.
        </p>
      </div>

      <section className="flex flex-col gap-[18px] rounded-3xl border border-line bg-white p-5 md:p-7">
        <div className="flex items-baseline gap-3">
          <div className="font-mono text-[13px] font-bold text-brand">01</div>
          <h2 className="text-xl font-bold">Remove the vig</h2>
        </div>
        <p className="text-[15px] leading-relaxed">
          Books price both sides so their implied probabilities add up to more than 100%.
          The extra is their margin. Dividing each side by the total gives the fair price.
          The consensus is the mean of those fair prices across the books that posted the line.
        </p>
        <div className="flex flex-col gap-2.5">
          <VigRow label="Over −110" fill="bg-brand" percent="52.38%" />
          <VigRow label="Under −110" fill="bg-brand-soft" percent="52.38%" />
          <div className="flex items-center gap-2 text-[13px] text-muted">
            <span className="h-3 w-3 rounded-[3px] bg-accent" />
            Vig: 104.76% − 100% = 4.76%. Fair price: 50% / 50%.
          </div>
        </div>
        <div className="overflow-x-auto rounded-2xl bg-dark px-[18px] py-4 font-mono text-[13px] leading-[1.9] text-[#EDE7F8]">
          <div>
            p = |odds| / (|odds| + 100) <span className="text-[#8F86A3]">{"// odds < 0"}</span>
          </div>
          <div>
            p = 100 / (odds + 100) <span className="text-[#8F86A3]">{"// odds > 0"}</span>
          </div>
          <div className="text-accent">p_fair = p / (p_over + p_under)</div>
          <div className="text-accent">consensus = mean(p_fair across books)</div>
        </div>
      </section>

      <section className="flex flex-col gap-4 rounded-3xl border border-line bg-white p-5 md:p-7">
        <div className="flex items-baseline gap-3">
          <div className="font-mono text-[13px] font-bold text-brand">02</div>
          <h2 className="text-xl font-bold">What the board actually shows</h2>
        </div>
        <p className="text-[15px] leading-relaxed text-ink">
          Each row below is its own field. Nothing on this list is weighted into the percent
          on Daily Picks.
        </p>
        <ul className="flex flex-col">
          <Signal
            label="Historical hit rate"
            detail="DailyPick.probability. How often the player landed on the stored side of the mode line. The sample size is n_games. The daily board keeps rows at or above 65% with at least 10 games."
          />
          <Signal
            label="No-vig consensus"
            detail="On a game page, the mean fair price from the no-vig route. It is not copied onto DailyPick.probability."
          />
          <Signal
            label="Projection"
            detail="Projected value, edge, and minutes stay hidden while those fields are null. WNBA picks leave them null, so those tags stay hidden."
          />
          <Signal
            label="Opponent rank"
            detail="opponent_rank or opponent_position_rank, shown as Def # only when the number is present. A null rank stays blank."
          />
        </ul>
        <p className="rounded-2xl bg-[#F6F2D2] px-4 py-3 text-sm leading-6 text-yellow">
          Planned: one blended probability, and Supports / Neutral / Against verdicts.
          The API does not return them, so this app does not show them.
        </p>
      </section>

      <section className="flex flex-col gap-3.5 rounded-3xl border border-line bg-white p-5 md:p-7">
        <div className="flex items-baseline gap-3">
          <div className="font-mono text-[13px] font-bold text-brand">03</div>
          <h2 className="text-xl font-bold">Read the tier</h2>
        </div>
        <p className="text-[15px] leading-relaxed">
          The tier is a display bucket on the historical hit rate. It is not a field the
          API sends, and it is not a verdict.
        </p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <Tier name="Strong play" range="≥ 70%" className="bg-accent text-brand-ink" />
          <Tier name="Playable" range="65 – 70%" className="bg-brand text-white" />
          <Tier name="Lean only" range="56 – 65%" className="bg-[#E3DAF3] text-brand" />
          <Tier name="Pass" range="< 56%" className="bg-[#E2E2E2] text-[#4A4458]" />
        </div>
        <p className="text-sm leading-6 text-muted">
          Lean only and Pass do not appear on Daily Picks with the current service, because
          rows below 65% or under 10 games are dropped before the page loads them.
        </p>
      </section>

      <section className="rounded-3xl border border-line bg-white p-5 md:p-7">
        <h2 className="text-lg font-bold">NBA and WNBA</h2>
        <p className="mt-3 text-sm leading-6 text-muted">
          Both leagues use the same no-vig formula and the same historical-rate board.
          Picks and slips stay on separate routes.
        </p>
        <ul className="mt-4 space-y-2 text-sm">
          <li>
            <span className="font-bold">NBA:</span>{" "}
            <Link href="/picks" className="font-semibold text-brand hover:underline">
              Daily Picks
            </Link>
            {" · "}
            <Link href="/betslip" className="font-semibold text-brand hover:underline">
              Bet Slip
            </Link>
          </li>
          <li>
            <span className="font-bold">WNBA:</span>{" "}
            <Link href="/wnba/picks" className="font-semibold text-brand hover:underline">
              Daily Picks
            </Link>
            {" · "}
            <Link href="/wnba/betslip" className="font-semibold text-brand hover:underline">
              Bet Slip
            </Link>
          </li>
        </ul>
        <p className="mt-4 text-sm text-muted">
          Odds come from{" "}
          <a
            href="https://the-odds-api.com"
            target="_blank"
            rel="noopener noreferrer"
            className="font-semibold text-brand hover:underline"
          >
            The Odds API
          </a>
          .
        </p>
      </section>

      <p className="text-[13px] leading-6 text-muted">
        For informational and research purposes only. This is not betting advice. Odds and
        lineup data may be delayed or missing; check official sources. Past results do not
        predict future results.
      </p>
    </div>
  );
}

function VigRow({ label, fill, percent }: { label: string; fill: string; percent: string }) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="w-[110px] font-mono text-[13px] font-semibold">{label}</div>
      <div className="relative h-[22px] min-w-[200px] flex-1 overflow-hidden rounded-md bg-[#EEEBF2]">
        <div className={`absolute inset-y-0 left-0 w-1/2 ${fill}`} />
        <div className="absolute inset-y-0 left-1/2 w-[2.4%] bg-accent" />
      </div>
      <div className="w-[70px] text-right font-mono text-[13px] font-bold">{percent}</div>
    </div>
  );
}

function Signal({ label, detail }: { label: string; detail: string }) {
  return (
    <li className="border-t border-[#EEEBF2] py-3">
      <div className="text-[15px] font-bold">{label}</div>
      <div className="mt-0.5 text-[13px] leading-6 text-muted">{detail}</div>
    </li>
  );
}

function Tier({ name, range, className }: { name: string; range: string; className: string }) {
  return (
    <div className={`rounded-2xl px-3.5 py-3.5 ${className}`}>
      <div className="font-bold">{name}</div>
      <div className="mt-1 font-mono text-[13px] font-semibold">{range}</div>
    </div>
  );
}
