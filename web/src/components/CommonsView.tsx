"use client";

import { useMemo } from "react";
import Link from "next/link";
import { FairValues, MarketSnapshot, ShareDilution, formatTime, formatUsd } from "@/lib/types";
import { AsstBalanceSheet, MstrBalanceSheet } from "@/components/BalanceSheets";
import { ShareCountsSection } from "@/components/ShareCountsSection";
import { liveAsstRnavTotals, liveRnavTotals } from "@/lib/rnav";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";

export function CommonsView({
  initialMarket,
  initialFair,
  dilution,
}: {
  initialMarket: MarketSnapshot;
  initialFair: FairValues;
  dilution: ShareDilution;
}) {
  const { asOf, btc, instruments, live, error } = useLiveQuotes(initialMarket);

  const mstrPx =
    instruments.find((i) => i.ticker === "MSTR")?.market_price ?? null;
  const asstPx =
    instruments.find((i) => i.ticker === "ASST")?.market_price ?? null;
  const sataPx =
    instruments.find((i) => i.ticker === "SATA")?.market_price ?? null;

  const mstrRnav = useMemo(
    () => liveRnavTotals(initialMarket, btc),
    [initialMarket, btc]
  );
  const asstRnav = useMemo(
    () => liveAsstRnavTotals(initialMarket, btc, sataPx, asstPx),
    [initialMarket, btc, sataPx, asstPx]
  );

  const comparison = [
    {
      ticker: "MSTR",
      market: mstrPx,
      fair: mstrRnav.marketPs,
    },
    {
      ticker: "ASST",
      market: asstPx,
      fair: asstRnav.marketPs,
    },
  ];

  return (
    <div className="relative mx-auto max-w-6xl px-5 py-14 md:px-8 md:py-16">
      <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
        Commons
      </p>
      <h1 className="mt-4 font-display text-4xl text-mist-100 md:text-5xl">
        Bitcoin treasuries
      </h1>
      <p className="mt-4 text-lg text-mist-300">
        rNAV — residual net asset value after senior claims.
      </p>
      <p className="mt-4 font-mono text-xs text-mist-500">
        {live ? "Live" : "Snapshot"} · {formatTime(asOf)}
        {error ? <span className="text-ember-400"> · {error}</span> : null}
      </p>

      <section className="mt-12">
        <h2 className="font-display text-3xl text-mist-100">
          Premium to rNAV
        </h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {comparison.map((row) => {
            const premium =
              row.market != null && row.fair != null && row.fair !== 0
                ? ((row.market - row.fair) / row.fair) * 100
                : null;
            return (
              <div
                key={row.ticker}
                className="border border-white/8 bg-ink-900/60 px-5 py-6"
              >
                <p className="font-display text-xl text-mist-100">{row.ticker}</p>
                <p
                  className={`mt-4 font-mono text-4xl tabular-nums tracking-tight md:text-5xl ${
                    premium == null
                      ? "text-mist-500"
                      : premium >= 0
                        ? "text-ember-400"
                        : "text-mint-400"
                  }`}
                >
                  {premium == null
                    ? "—"
                    : `${premium >= 0 ? "+" : ""}${premium.toFixed(1)}%`}
                </p>
                <p className="mt-2 font-mono text-xs text-mist-500">
                  mkt {formatUsd(row.market)} · rNAV {formatUsd(row.fair)}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Balance sheets</h2>
        <p className="mt-2 text-mist-400">
          Face value vs market value.
        </p>
        <div className="mt-8 grid gap-6 lg:grid-cols-2 lg:items-stretch">
          <MstrBalanceSheet
            market={initialMarket}
            btc={btc}
            mstrPrice={mstrPx}
          />
          <AsstBalanceSheet
            market={initialMarket}
            btc={btc}
            asstPrice={asstPx}
            sataPrice={sataPx}
          />
        </div>
        <p className="mt-6 text-sm text-mist-500">
          <span className="text-ember-400">*</span> STRE has no reliable
          Nasdaq/Yahoo mark (LuxSE), so both columns use €100×FX face; other
          preferreds and converts are at par/face vs market; MSTR/share and
          premium use live price vs each rNAV/share.
        </p>
      </section>

      <div className="mt-16">
        <ShareCountsSection dilution={dilution} />
      </div>

      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Methodology</h2>
        <ol className="mt-8 space-y-8">
          <li>
            <h3 className="font-display text-xl text-mist-100">
              1. Mark the treasury
            </h3>
            <p className="mt-2 text-mist-400">
              Start with Bitcoin holdings marked at spot, plus cash.
            </p>
          </li>
          <li>
            <h3 className="font-display text-xl text-mist-100">
              2. Subtract senior claims
            </h3>
            <p className="mt-2 text-mist-400">
              Subtract debt and preferreds twice — once at face and once at
              market. What remains is rNAV.
            </p>
          </li>
          <li>
            <h3 className="font-display text-xl text-mist-100">
              3. Divide by diluted commons
            </h3>
            <p className="mt-2 text-mist-400">
              Divide by basic shares plus options, RSUs, and ITM warrants.
              Converts, STRK, OTM warrants, and preferreds stay off the share
              count; they are already claims in step 2.
            </p>
          </li>
        </ol>
        <p className="mt-10">
          <Link href="/preferreds" className="text-ember-400 hover:underline">
            Compare preferreds →
          </Link>
        </p>
      </section>
    </div>
  );
}
