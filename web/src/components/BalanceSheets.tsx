"use client";

import { useState } from "react";
import {
  formatCompact,
  formatUsd,
  MarketSnapshot,
} from "@/lib/types";
import { liveAsstRnavTotals, liveRnavTotals } from "@/lib/rnav";

export function MstrBalanceSheet({
  market,
  btc,
  mstrPrice,
}: {
  market: MarketSnapshot;
  btc: number;
  mstrPrice: number | null;
}) {
  const [prefsOpen, setPrefsOpen] = useState(false);
  const rnav = market.mstr.rnav;
  const live = liveRnavTotals(market, btc);

  const debtMkt =
    rnav?.convertible_debt_market ?? market.mstr.convertible_debt_market_value;
  const debtFace =
    rnav?.convertible_debt_face ?? market.mstr.convertible_debt_principal;
  const prefMkt = rnav?.preferred_market_cap ?? 0;
  const prefFace = rnav?.preferred_face_cap ?? 0;
  const streFace = rnav?.stre_face_usd ?? 0;
  const byMkt = rnav?.preferred_by_series ?? {};
  const byFace = rnav?.preferred_face_by_series ?? {};
  const strfCMkt = (byMkt.strf ?? 0) + (byMkt.strc ?? 0);
  const strfCFace = (byFace.strf ?? 0) + (byFace.strc ?? 0);
  const strkDMkt = (byMkt.strk ?? 0) + (byMkt.strd ?? 0);
  const strkDFace = (byFace.strk ?? 0) + (byFace.strd ?? 0);
  const prefsMktTotal = prefMkt + streFace;
  const prefsFaceTotal = prefFace + streFace;
  const cash = rnav?.cash ?? market.mstr.usd_reserve_usd ?? 0;
  const btcNav = (rnav?.btc_holdings ?? market.mstr.btc_holdings ?? 0) * btc;
  const rnavFace = live.face ?? rnav?.rnav_face_total;
  const rnavMkt = live.market ?? rnav?.rnav_market_total;
  const facePs = live.facePs ?? rnav?.rnav_face_per_share ?? null;
  const mktPs = live.marketPs ?? rnav?.rnav_market_per_share ?? null;
  const cell = "py-2 align-top tabular-nums";
  const muted = "text-mist-500";

  return (
    <div className="flex h-full flex-col border border-white/8 bg-ink-900/60 p-5">
      <h3 className="font-display text-xl text-mist-100">MSTR Balance Sheet</h3>
      <table className="mt-5 w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left text-[10px] uppercase tracking-[0.14em] text-mist-500">
            <th className="pb-2 font-normal"> </th>
            <th className="pb-2 text-right font-normal">rNAV face</th>
            <th className="pb-2 text-right font-normal text-ember-400">
              rNAV mkt
            </th>
          </tr>
        </thead>
        <tbody className="text-mist-300">
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Bitcoin NAV</td>
            <td className={`${cell} text-right text-mist-100`}>
              {formatCompact(btcNav)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              {formatCompact(btcNav)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Cash</td>
            <td className={`${cell} text-right text-mist-100`}>
              {formatCompact(cash)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              {formatCompact(cash)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Debt</td>
            <td className={`${cell} text-right text-mist-100`}>
              −{formatCompact(debtFace)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              −{formatCompact(debtMkt)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>
              <button
                type="button"
                onClick={() => setPrefsOpen((o) => !o)}
                aria-expanded={prefsOpen}
                className="inline-flex items-center gap-1.5 text-mist-400 transition hover:text-mist-100"
              >
                <span
                  className="inline-block text-[10px] text-ember-400 transition-transform"
                  style={{
                    transform: prefsOpen ? "rotate(90deg)" : "none",
                  }}
                  aria-hidden
                >
                  ▸
                </span>
                Preferreds
              </button>
            </td>
            <td className={`${cell} text-right text-mist-100`}>
              −{formatCompact(prefsFaceTotal)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              −{formatCompact(prefsMktTotal)}
            </td>
          </tr>
          {prefsOpen ? (
            <>
              <tr className="border-b border-white/5">
                <td className={`${cell} pl-5 text-mist-500`}>STRF / C</td>
                <td className={`${cell} text-right text-mist-400`}>
                  −{formatCompact(strfCFace)}
                </td>
                <td className={`${cell} text-right text-ember-400`}>
                  −{formatCompact(strfCMkt)}
                </td>
              </tr>
              <tr className="border-b border-white/5">
                <td className={`${cell} pl-5 text-mist-500`}>
                  STRE
                  <span className="text-ember-400" aria-hidden>
                    *
                  </span>
                </td>
                <td className={`${cell} text-right text-mist-400`}>
                  −{formatCompact(streFace)}
                </td>
                <td className={`${cell} text-right text-ember-400`}>
                  −{formatCompact(streFace)}
                </td>
              </tr>
              <tr className="border-b border-white/5">
                <td className={`${cell} pl-5 text-mist-500`}>STRK / D</td>
                <td className={`${cell} text-right text-mist-400`}>
                  −{formatCompact(strkDFace)}
                </td>
                <td className={`${cell} text-right text-ember-400`}>
                  −{formatCompact(strkDMkt)}
                </td>
              </tr>
            </>
          ) : null}
          <tr className="border-b border-white/5">
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              Total equity
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {formatCompact(rnavFace)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {formatCompact(rnavMkt)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              MSTR / share
              <span className={`mt-0.5 block text-[10px] ${muted}`}>
                mkt {formatUsd(mstrPrice)}
              </span>
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {formatUsd(facePs)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {formatUsd(mktPs)}
            </td>
          </tr>
          <tr>
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              Premium
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {premiumPct(mstrPrice, facePs)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {premiumPct(mstrPrice, mktPs)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function AsstBalanceSheet({
  market,
  btc,
  asstPrice,
  sataPrice,
}: {
  market: MarketSnapshot;
  btc: number;
  asstPrice: number | null;
  sataPrice: number | null;
}) {
  const [prefsOpen, setPrefsOpen] = useState(false);
  const live = liveAsstRnavTotals(market, btc, sataPrice, asstPrice);
  const {
    face: rnavFace,
    market: rnavMkt,
    facePs,
    marketPs: mktPs,
    sataFace,
    sataMkt,
    btcNav,
    cash,
    debt,
  } = live;
  const cell = "py-2 align-top tabular-nums";
  const muted = "text-mist-500";

  return (
    <div className="flex h-full flex-col border border-white/8 bg-ink-900/60 p-5">
      <h3 className="font-display text-xl text-mist-100">ASST Balance Sheet</h3>
      <table className="mt-5 w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left text-[10px] uppercase tracking-[0.14em] text-mist-500">
            <th className="pb-2 font-normal"> </th>
            <th className="pb-2 text-right font-normal">rNAV face</th>
            <th className="pb-2 text-right font-normal text-ember-400">
              rNAV mkt
            </th>
          </tr>
        </thead>
        <tbody className="text-mist-300">
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Bitcoin NAV</td>
            <td className={`${cell} text-right text-mist-100`}>
              {formatCompact(btcNav)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              {formatCompact(btcNav)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Cash</td>
            <td className={`${cell} text-right text-mist-100`}>
              {formatCompact(cash)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              {formatCompact(cash)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>Debt</td>
            <td className={`${cell} text-right text-mist-100`}>
              −{formatCompact(debt)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              −{formatCompact(debt)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} text-mist-400`}>
              <button
                type="button"
                onClick={() => setPrefsOpen((o) => !o)}
                aria-expanded={prefsOpen}
                className="inline-flex items-center gap-1.5 text-mist-400 transition hover:text-mist-100"
              >
                <span
                  className="inline-block text-[10px] text-ember-400 transition-transform"
                  style={{
                    transform: prefsOpen ? "rotate(90deg)" : "none",
                  }}
                  aria-hidden
                >
                  ▸
                </span>
                Preferreds
              </button>
            </td>
            <td className={`${cell} text-right text-mist-100`}>
              −{formatCompact(sataFace)}
            </td>
            <td className={`${cell} text-right text-ember-400`}>
              −{formatCompact(sataMkt)}
            </td>
          </tr>
          {prefsOpen ? (
            <tr className="border-b border-white/5">
              <td className={`${cell} pl-5 text-mist-500`}>SATA</td>
              <td className={`${cell} text-right text-mist-400`}>
                −{formatCompact(sataFace)}
              </td>
              <td className={`${cell} text-right text-ember-400`}>
                −{formatCompact(sataMkt)}
              </td>
            </tr>
          ) : null}
          <tr className="border-b border-white/5">
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              Total equity
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {formatCompact(rnavFace)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {formatCompact(rnavMkt)}
            </td>
          </tr>
          <tr className="border-b border-white/5">
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              ASST / share
              <span className={`mt-0.5 block text-[10px] ${muted}`}>
                mkt {formatUsd(asstPrice)}
              </span>
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {formatUsd(facePs)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {formatUsd(mktPs)}
            </td>
          </tr>
          <tr>
            <td className={`${cell} pt-3 font-medium text-mist-200`}>
              Premium
            </td>
            <td className={`${cell} pt-3 text-right text-mist-100`}>
              {premiumPct(asstPrice, facePs)}
            </td>
            <td className={`${cell} pt-3 text-right text-ember-400`}>
              {premiumPct(asstPrice, mktPs)}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function premiumPct(price: number | null, fairPs: number | null) {
  if (price == null || fairPs == null || fairPs === 0) return "—";
  const pct = ((price - fairPs) / fairPs) * 100;
  const sign = pct > 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}
