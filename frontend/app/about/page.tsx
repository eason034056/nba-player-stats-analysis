/**
 * /about — Method, shared by NBA and WNBA.
 *
 * The blend copy mirrors backend/app/services/pick_signals.py and
 * pick_signal_constants.py. Change them together.
 */

import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Method",
  description:
    "How No-Vig reads a prop: remove the bookmaker margin, then weigh the fair price against the player's own numbers.",
};

const BLEND_SIGNALS: ReadonlyArray<{ label: string; detail: string; role: string }> = [
  {
    label: "Market price",
    detail: "No-vig consensus for the side, across the books that post the line. Without it there is no combined probability.",
    role: "Base",
  },
  {
    label: "Last 10 games",
    detail: "How often the player cleared the line in the last 10 games.",
    role: "± 0.15",
  },
  {
    label: "All-game hit rate",
    detail: "How often the player cleared the line across the stored game log.",
    role: "± 0.15",
  },
  {
    label: "Opponent defense",
    detail: "Where the opponent ranks against the player's position.",
    role: "± 0.15",
  },
  {
    label: "Projection",
    detail: "Not used yet. It returns when a projection model ships.",
    role: "Off",
  },
];

export default function AboutPage() {
  return (
    <div className="mx-auto flex w-full max-w-[880px] flex-col gap-[22px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-col gap-2.5">
        <h1 className="text-[32px] font-bold leading-none tracking-[-0.035em] md:text-[52px]">
          How we read a prop
        </h1>
        <p className="max-w-[720px] text-base leading-relaxed text-muted">
          Two steps: strip the bookmaker margin out of the price, then weigh that fair price
          against the player&apos;s own numbers.
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
          <h2 className="text-xl font-bold">Blend the signals</h2>
        </div>
        <p className="text-[15px] leading-relaxed text-ink">
          On NBA the market price is the starting point. Recent form, the all-game hit rate,
          and the opponent&apos;s defense nudge it up or down. Each nudge is capped, and so is
          their sum, so no single number overrides the market. On a game page each signal also
          says whether it supports the side.
        </p>
        <ul aria-label="Signals in the blend" className="flex flex-col">
          {BLEND_SIGNALS.map((signal) => (
            <Signal key={signal.label} {...signal} />
          ))}
        </ul>
        <div className="overflow-x-auto rounded-2xl bg-dark px-[18px] py-4 font-mono text-[13px] leading-[1.9] text-[#EDE7F8]">
          <div>
            nudges = last10 + all_game + defense{" "}
            <span className="text-[#8F86A3]">{"// each capped at ± 0.15 log-odds"}</span>
          </div>
          <div className="text-accent">p = sigmoid(logit(consensus) + a + b × clip(nudges, ± 0.35))</div>
        </div>
        <p className="text-sm leading-6 text-muted">
          a and b are fit on past regular-season games. A player listed Out gets no number.
          WNBA picks have no market blend yet, so their percent is the historical hit rate.
        </p>
      </section>

      <section className="flex flex-col gap-3.5 rounded-3xl border border-line bg-white p-5 md:p-7">
        <div className="flex items-baseline gap-3">
          <div className="font-mono text-[13px] font-bold text-brand">03</div>
          <h2 className="text-xl font-bold">Read the tier</h2>
        </div>
        <p className="text-[15px] leading-relaxed">
          The tier is a bucket on the percent you see: the combined probability on NBA, the
          historical hit rate on WNBA. The API sends it with each read.
        </p>
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
          <Tier name="Strong play" range="≥ 70%" className="bg-accent text-brand-ink" />
          <Tier name="Playable" range="65 – 70%" className="bg-brand text-white" />
          <Tier name="Lean only" range="56 – 65%" className="bg-[#E3DAF3] text-brand" />
          <Tier name="Pass" range="< 56%" className="bg-[#E2E2E2] text-[#4A4458]" />
        </div>
        <p className="text-sm leading-6 text-muted">
          Daily Picks lists Strong play and Playable. Lean only shows up on a game page, where
          every posted player gets a read. Below 56% there is no tier.
        </p>
      </section>

      <section className="rounded-3xl border border-line bg-white p-5 md:p-7">
        <h2 className="text-lg font-bold">NBA and WNBA</h2>
        <p className="mt-3 text-sm leading-6 text-muted">
          Both leagues use the same no-vig formula. NBA blends it with the player&apos;s
          numbers. WNBA shows the historical hit rate. Picks and slips stay on separate routes.
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

function Signal({ label, detail, role }: { label: string; detail: string; role: string }) {
  return (
    <li className="flex items-center gap-4 border-t border-[#EEEBF2] py-3">
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-bold">{label}</div>
        <div className="mt-0.5 text-[13px] leading-6 text-muted">{detail}</div>
      </div>
      <div className="shrink-0 font-mono text-[13px] font-bold text-brand">{role}</div>
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
