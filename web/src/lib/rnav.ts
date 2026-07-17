import { FairValues, MarketSnapshot } from "@/lib/types";

const SATA_PAR = 100;

export function fairFor(fairData: FairValues, ticker: string) {
  return fairData.tickers.find((t) => t.ticker === ticker);
}

export function gapPctFor(market: number | null, fair: number | null) {
  if (market == null || fair == null || market === 0) return null;
  return ((fair - market) / market) * 100;
}

export function liveRnavTotals(
  market: MarketSnapshot,
  btcPrice: number
): {
  face: number | null;
  market: number | null;
  facePs: number | null;
  marketPs: number | null;
} {
  const r = market.mstr.rnav;
  const shares = r?.mstr_shares ?? 0;
  if (!r || shares <= 0) {
    return { face: null, market: null, facePs: null, marketPs: null };
  }
  const holdings = r.btc_holdings ?? market.mstr.btc_holdings ?? 0;
  const cash = r.cash ?? market.mstr.usd_reserve_usd ?? 0;
  const stre = r.stre_face_usd ?? 0;
  const prefFace = (r.preferred_face_cap ?? 0) + stre;
  const prefMkt = (r.preferred_market_cap ?? 0) + stre;
  const debtFace =
    r.convertible_debt_face ?? market.mstr.convertible_debt_principal ?? 0;
  const debtMkt =
    r.convertible_debt_market ?? market.mstr.convertible_debt_market_value ?? 0;
  const face = holdings * btcPrice + cash - prefFace - debtFace;
  const mkt = holdings * btcPrice + cash - prefMkt - debtMkt;
  return {
    face,
    market: mkt,
    facePs: face / shares,
    marketPs: mkt / shares,
  };
}

export function liveAsstRnavTotals(
  market: MarketSnapshot,
  btcPrice: number,
  sataPrice: number | null,
  asstPrice: number | null
): {
  face: number | null;
  market: number | null;
  facePs: number | null;
  marketPs: number | null;
  sataFace: number;
  sataMkt: number;
  btcNav: number;
  cash: number;
  debt: number;
} {
  const r = market.asst.rnav;
  const holdings = r?.btc_holdings ?? market.asst.btc_holdings ?? 0;
  const cash = r?.cash ?? market.asst.cash ?? 0;
  const debt = r?.debt ?? market.asst.debt ?? 0;
  const sataShares = r?.sata_shares ?? market.asst.sata_shares ?? 0;
  const sataFace = sataShares * SATA_PAR;
  const sataPx = sataPrice ?? r?.sata_price ?? null;
  const sataMkt =
    sataShares > 0 && sataPx != null && sataPx > 0
      ? sataShares * sataPx
      : sataFace;
  const btcNav = holdings * btcPrice;
  const face = btcNav + cash - sataFace - debt;
  const mkt = btcNav + cash - sataMkt - debt;

  let shares = r?.asst_shares ?? 0;
  const mcap = market.asst.mcap ?? 0;
  if (shares <= 0 && mcap > 0 && asstPrice != null && asstPrice > 0) {
    shares = mcap / asstPrice;
  }

  return {
    face,
    market: mkt,
    facePs: shares > 0 ? face / shares : null,
    marketPs: shares > 0 ? mkt / shares : null,
    sataFace,
    sataMkt,
    btcNav,
    cash,
    debt,
  };
}
