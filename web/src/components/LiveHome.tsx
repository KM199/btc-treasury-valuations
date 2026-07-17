"use client";

import { useMemo } from "react";
import Link from "next/link";
import { FairValues, Instrument, MarketSnapshot, formatTime, formatUsd } from "@/lib/types";
import { fairFor, gapPctFor, liveAsstRnavTotals, liveRnavTotals } from "@/lib/rnav";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";

const TILE_HREF: Record<string, string> = {
  MSTR: "/commons",
  ASST: "/commons",
  STRC: "/preferreds",
  SATA: "/preferreds",
};

export function LiveHome({
  initialMarket,
  initialFair,
}: {
  initialMarket: MarketSnapshot;
  initialFair: FairValues;
}) {
  const { asOf, btc, instruments, live, error } = useLiveQuotes(initialMarket);

  const mstrRnavLive = useMemo(
    () => liveRnavTotals(initialMarket, btc),
    [initialMarket, btc]
  );

  const sataPxLive =
    instruments.find((i) => i.ticker === "SATA")?.market_price ?? null;
  const asstPxLive =
    instruments.find((i) => i.ticker === "ASST")?.market_price ?? null;

  const asstRnavLive = useMemo(
    () => liveAsstRnavTotals(initialMarket, btc, sataPxLive, asstPxLive),
    [initialMarket, btc, sataPxLive, asstPxLive]
  );

  const fairByTicker = useMemo(() => {
    const map = new Map<string, number | null>();
    for (const t of initialFair.tickers) {
      map.set(t.ticker, t.fair_value);
    }
    if (mstrRnavLive.marketPs != null) map.set("MSTR", mstrRnavLive.marketPs);
    if (asstRnavLive.marketPs != null) map.set("ASST", asstRnavLive.marketPs);
    return map;
  }, [initialFair, mstrRnavLive, asstRnavLive]);

  return (
    <div className="relative overflow-hidden">
      <div
        className="pointer-events-none absolute inset-0 bg-grid-fade opacity-40"
        style={{ backgroundSize: "48px 48px" }}
      />
      <div className="animate-drift pointer-events-none absolute -right-24 top-24 h-72 w-72 rounded-full bg-ember-500/10 blur-3xl" />

      <section className="relative mx-auto max-w-6xl px-5 pb-10 pt-14 md:px-8 md:pt-20">
        <h1 className="animate-rise font-display text-5xl tracking-tight text-mist-100 md:text-7xl">
          HEDGD
        </h1>
        <p className="animate-rise-delay-1 mt-4 max-w-3xl text-xl leading-snug text-mist-300 md:text-2xl">
          Intrinsic value of Bitcoin treasuries and their preferreds.
        </p>
        <p className="animate-rise-delay-2 mt-6 font-mono text-xs text-mist-500">
          {live ? "Live" : "Snapshot"} · {formatTime(asOf)}
          {error ? <span className="text-ember-400"> · {error}</span> : null}
        </p>
      </section>

      <section className="relative mx-auto max-w-6xl px-5 pb-24 md:px-8">
        <div className="grid grid-cols-2 gap-8 border-y border-white/10 py-10 lg:gap-10">
          {(["MSTR", "ASST", "STRC", "SATA"] as const).map((ticker, i) => {
            const inst = instruments.find((x) => x.ticker === ticker);
            if (!inst) return null;
            const fairVal = fairByTicker.get(inst.ticker) ?? null;
            const gapPct = gapPctFor(inst.market_price, fairVal);
            const label =
              ticker === "MSTR" || ticker === "ASST"
                ? "rNAV"
                : fairFor(initialFair, ticker)?.fair_label;
            return (
              <InstrumentTile
                key={ticker}
                href={TILE_HREF[ticker]}
                inst={inst}
                fairVal={fairVal}
                gapPct={gapPct}
                fairLabel={label}
                delay={0.05 * i}
              />
            );
          })}
        </div>
      </section>
    </div>
  );
}

function InstrumentTile({
  href,
  inst,
  fairVal,
  gapPct,
  fairLabel,
  delay,
}: {
  href: string;
  inst: Instrument;
  fairVal: number | null;
  gapPct: number | null;
  fairLabel?: string;
  delay: number;
}) {
  return (
    <Link
      href={href}
      className="animate-rise group block transition-colors hover:bg-white/[0.02]"
      style={{ animationDelay: `${delay}s` }}
    >
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="font-display text-2xl text-mist-100 transition-colors group-hover:text-ember-400">
          {inst.ticker}
        </h2>
        <span className="font-mono text-[10px] uppercase tracking-wider text-mist-500">
          {inst.kind}
        </span>
      </div>
      <p className="mt-1 text-sm text-mist-500">{inst.name}</p>
      <p className="mt-6 font-mono text-3xl tabular-nums tracking-tight text-mist-100">
        {formatUsd(inst.market_price)}
      </p>
      <p className="mt-1 text-xs text-mist-500">Market</p>
      <div className="mt-5">
        <p className="font-mono text-xl tabular-nums text-ember-400">
          {fairVal != null ? formatUsd(fairVal) : "—"}
        </p>
        <p className="mt-1 text-xs text-mist-500">
          {fairLabel ? `${fairLabel} ` : "Model fair"}
          {gapPct != null ? (
            <span className={gapPct >= 0 ? " text-mint-400" : " text-ember-400"}>
              · {gapPct >= 0 ? "+" : ""}
              {gapPct.toFixed(1)}%
            </span>
          ) : null}
        </p>
      </div>
    </Link>
  );
}
