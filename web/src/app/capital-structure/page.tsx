import Link from "next/link";
import {
  formatCompact,
  formatUsd,
  MarketSnapshot,
} from "@/lib/types";
import marketJson from "../../../public/data/market_snapshot.json";

type WipeoutLayer = {
  name: string;
  kind: string;
  claim_usd?: number | null;
  senior_claims_usd?: number;
  btc_full?: number | null;
  btc_zero?: number | null;
  buffer_to_zero_pct?: number | null;
  note?: string;
};

type WipeoutLadder = {
  btc_spot?: number;
  btc_holdings?: number;
  cash?: number;
  layers?: WipeoutLayer[];
  strc_par_band?: {
    btc_par?: number | null;
    btc_zero?: number | null;
    note?: string;
  };
  basis?: Record<string, string | number>;
};

function formatBtc(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

function formatBuffer(pct: number | null | undefined): string {
  if (pct == null || Number.isNaN(pct)) return "—";
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(0)}%`;
}

function WipeoutTable({
  title,
  ladder,
}: {
  title: string;
  ladder: WipeoutLadder | undefined;
}) {
  const layers = ladder?.layers || [];
  if (!layers.length) {
    return (
      <div className="border border-white/8 bg-ink-900/60 p-5">
        <h2 className="font-display text-2xl text-mist-100">{title}</h2>
        <p className="mt-3 text-sm text-mist-500">Wipeout data unavailable.</p>
      </div>
    );
  }

  const cell = "py-2.5 align-top tabular-nums";

  return (
    <div className="border border-white/8 bg-ink-900/60 p-5 md:p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-display text-2xl text-mist-100 md:text-3xl">
          {title}
        </h2>
        <p className="font-mono text-xs text-mist-500">
          BTC now {formatBtc(ladder?.btc_spot)}
        </p>
      </div>

      <table className="mt-8 w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left text-[10px] uppercase tracking-[0.14em] text-mist-500">
            <th className="pb-2 font-normal">Claim</th>
            <th className="pb-2 text-right font-normal">Size</th>
            <th className="pb-2 text-right font-normal text-ember-400">
              BTC wipeout
            </th>
            <th className="pb-2 text-right font-normal">Buffer</th>
          </tr>
        </thead>
        <tbody className="text-mist-300">
          {layers.map((layer, i) => (
            <tr key={layer.name} className="border-b border-white/5">
              <td className={`${cell} text-mist-200`}>
                <span className="text-mist-500">{i + 1}. </span>
                {layer.name}
              </td>
              <td className={`${cell} text-right text-mist-100`}>
                {layer.claim_usd == null ? "residual" : formatCompact(layer.claim_usd)}
              </td>
              <td className={`${cell} text-right text-ember-400`}>
                {formatBtc(layer.btc_zero ?? 0)}
              </td>
              <td className={`${cell} text-right text-mist-400`}>
                {formatBuffer(layer.buffer_to_zero_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function CapitalStructurePage() {
  const market = marketJson as unknown as MarketSnapshot & {
    mstr: MarketSnapshot["mstr"] & { wipeouts?: WipeoutLadder };
    asst: MarketSnapshot["asst"] & { wipeouts?: WipeoutLadder };
  };
  const mstr = market.mstr.wipeouts;
  const asst = market.asst.wipeouts;
  const band = mstr?.strc_par_band;

  return (
    <article className="mx-auto max-w-6xl px-5 py-16 md:px-8">
      <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
        Capital structure
      </p>
      <h1 className="mt-4 max-w-3xl font-display text-4xl text-mist-100 md:text-5xl">
        BTC wipeouts down the stack
      </h1>
      <p className="mt-6 max-w-2xl text-lg text-mist-300">
        Senior claims first. BTC wipeout is where that layer goes to zero.
        Buffer is the BTC move from spot down to wipeout (negative = room).
      </p>

      <div className="mt-14 grid gap-6 lg:grid-cols-2 lg:items-start">
        <WipeoutTable title="Strategy (MSTR)" ladder={mstr} />
        <WipeoutTable title="Strive (ASST)" ladder={asst} />
      </div>

      <div className="mt-14 max-w-2xl space-y-4 text-mist-300">
        <h2 className="font-display text-xl text-mist-100">Principles</h2>
        <p>
          Order is seniority: converts, then STRF / C / STRE / K / D, then
          common.
        </p>
        <p>
          Assets = Bitcoin × spot + cash. A layer wipes when assets only cover
          everyone above it.
        </p>
        <p>
          Claim sizes are face / contractual amounts — convert notional,
          preferred $100 par (STRE at €100×FX). Market prices are for rNAV
          elsewhere, not for these wipeouts.
        </p>
        {band?.btc_par != null && band?.btc_zero != null ? (
          <p>
            STRC contractual par band (seniors = converts + STRF only): full at{" "}
            <span className="font-mono text-mist-100">
              {formatBtc(band.btc_par)}
            </span>
            , zero at{" "}
            <span className="font-mono text-ember-400">
              {formatBtc(band.btc_zero)}
            </span>
            .
          </p>
        ) : null}
        <p className="text-sm text-mist-500">
          Cash on hand {formatCompact(mstr?.cash)} · Strategy BTC{" "}
          {mstr?.btc_holdings?.toLocaleString() ?? "—"} · spot{" "}
          {formatUsd(market.btc_price, 0)}.
        </p>
      </div>

      <p className="mt-12 flex flex-wrap gap-x-6 gap-y-2 text-sm">
        <Link href="/" className="text-ember-400 hover:underline">
          ← Back to values
        </Link>
        <Link href="/commons#share-counts" className="text-mist-400 hover:underline">
          Share counts
        </Link>
      </p>
    </article>
  );
}
