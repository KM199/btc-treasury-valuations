"use client";

import { useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import {
  FairValues,
  MarketSnapshot,
  PreferredIssuerStory,
  PreferredStory,
  formatCompact,
  formatTime,
  formatUsd,
} from "@/lib/types";
import {
  BtcPathFanChart,
  CumulativePvChart,
  DensityHistogramChart,
  FairVsBtcChart,
  HedgeComparisonChart,
  HedgePnlChart,
  SensitivityLineChart,
  StrcWipeoutBand,
} from "@/components/PreferredCharts";
import { fairFor } from "@/lib/rnav";
import { useLiveQuotes } from "@/hooks/useLiveQuotes";

function interpolateFair(
  scenarios: NonNullable<PreferredIssuerStory["scenarios"]>,
  btc: number
): number | null {
  const pts = scenarios
    .filter((s) => s.btc_start != null && s.fair_value != null)
    .map((s) => ({ x: s.btc_start as number, y: s.fair_value as number }))
    .sort((a, b) => a.x - b.x);
  if (!pts.length) return null;
  if (btc <= pts[0].x) return pts[0].y;
  if (btc >= pts[pts.length - 1].x) return pts[pts.length - 1].y;
  for (let i = 0; i < pts.length - 1; i++) {
    const a = pts[i];
    const b = pts[i + 1];
    if (btc >= a.x && btc <= b.x) {
      const t = (btc - a.x) / (b.x - a.x || 1);
      return a.y + t * (b.y - a.y);
    }
  }
  return null;
}

function nearestPoint<T extends Record<string, number | null | undefined>>(
  rows: T[],
  key: string,
  target: number
): T | null {
  if (!rows.length) return null;
  let best = rows[0];
  let bestDist = Infinity;
  for (const row of rows) {
    const v = row[key];
    if (v == null) continue;
    const d = Math.abs(Number(v) - target);
    if (d < bestDist) {
      bestDist = d;
      best = row;
    }
  }
  return best;
}

/** Range input that only lands on discrete grid values (chart points). */
function GridSlider({
  values,
  value,
  onChange,
  className = "mt-2 w-full accent-ember-400",
}: {
  values: number[];
  value: number;
  onChange: (v: number) => void;
  className?: string;
}) {
  const sorted = useMemo(
    () => [...values].filter((v) => Number.isFinite(v)).sort((a, b) => a - b),
    [values]
  );
  if (sorted.length < 2) return null;
  let idx = 0;
  let best = Infinity;
  for (let i = 0; i < sorted.length; i++) {
    const d = Math.abs(sorted[i] - value);
    if (d < best) {
      best = d;
      idx = i;
    }
  }
  return (
    <input
      type="range"
      min={0}
      max={sorted.length - 1}
      step={1}
      value={idx}
      onChange={(e) => onChange(sorted[Number(e.target.value)])}
      className={className}
    />
  );
}

function monthsToPriceClient(
  monthlyPayment: number,
  annualRate: number,
  target: number
): number | null {
  if (monthlyPayment <= 0 || target <= 0) return null;
  const r = Math.pow(1 + annualRate, 1 / 12) - 1;
  const npv = (months: number) => {
    let s = 0;
    for (let n = 1; n <= months; n++) s += monthlyPayment / Math.pow(1 + r, n);
    return s;
  };
  let low = 1;
  let high = 10000;
  if (npv(high) < target) return null;
  while (low < high) {
    const mid = Math.floor((low + high) / 2);
    if (npv(mid) < target) low = mid + 1;
    else high = mid;
  }
  return low;
}

function cumulativePvCurveClient(
  monthlyPayment: number,
  annualRate: number,
  maxMonths: number
): Array<{ month: number; pv: number }> {
  if (monthlyPayment <= 0 || maxMonths <= 0) return [];
  const r = Math.pow(1 + annualRate, 1 / 12) - 1;
  const out: Array<{ month: number; pv: number }> = [];
  let cum = 0;
  for (let n = 1; n <= maxMonths; n++) {
    cum +=
      Math.abs(r) < 1e-15
        ? monthlyPayment
        : monthlyPayment / Math.pow(1 + r, n);
    out.push({ month: n, pv: cum });
  }
  return out;
}

function pct(n: number | null | undefined, digits = 1) {
  if (n == null || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function PreferredsView({
  initialMarket,
  initialFair,
  story,
}: {
  initialMarket: MarketSnapshot;
  initialFair: FairValues;
  story: PreferredStory;
}) {
  const { asOf, instruments, live, error, btc } = useLiveQuotes(initialMarket);

  const sataStory = story.issuers.SATA;
  const ready = sataStory?.status === "ready" ? sataStory : null;

  const sataPx =
    instruments.find((i) => i.ticker === "SATA")?.market_price ?? null;

  const sataFair =
    ready?.baseline?.fair_value ??
    fairFor(initialFair, "SATA")?.fair_value ??
    null;

  // STRC's model fair value is intentionally not shown: the engine assumes
  // STRC has sole claim on MSTR's entire consolidated BTC/cash treasury, with
  // no allowance for convertible debt, STRF, or the other preferred series
  // that also sit ahead of or alongside it. Until the model accounts for
  // MSTR's actual capital-structure seniority, its STRC output is misleading.
  const premiumRows = [{ ticker: "SATA", market: sataPx, fair: sataFair }];

  const cfg = ready?.configuration || {};
  const scenarios = ready?.scenarios || [];
  const btcStarts = scenarios
    .map((s) => s.btc_start)
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b);
  const baselineBtc =
    scenarios.find((s) => Math.abs(Number(s.btc_start_pct || 0)) < 1e-9)
      ?.btc_start ??
    btcStarts[Math.floor(btcStarts.length / 2)] ??
    btc;

  const [btcSlider, setBtcSlider] = useState<number | null>(null);
  const activeBtc = btcSlider ?? baselineBtc ?? btc;
  const sliderFair = useMemo(
    () => interpolateFair(scenarios, activeBtc),
    [scenarios, activeBtc]
  );

  const threshRows = ready?.threshold_sensitivity || [];
  const divRows = ready?.dividend_rate_sensitivity || [];

  const baselineThresh = Number(cfg.dividend_suspension_threshold_multiplier ?? 1);
  const baselineDiv = Number(cfg.annual_dividend_rate ?? cfg.sata_annual_dividend_rate ?? 0.13);

  const [threshSlider, setThreshSlider] = useState<number | null>(null);
  const [divSlider, setDivSlider] = useState<number | null>(null);

  const threshActive = threshSlider ?? baselineThresh;
  const divActive = divSlider ?? baselineDiv;

  const threshHit = nearestPoint(threshRows, "threshold_multiplier", threshActive);
  const divHit = nearestPoint(divRows, "dividend_rate", divActive);

  const threshX = Number(threshHit?.threshold_multiplier ?? threshActive);
  const divX = Number(divHit?.dividend_rate ?? divActive);

  const threshValues = threshRows
    .map((r) => Number(r.threshold_multiplier))
    .filter((v) => Number.isFinite(v));
  const divValues = divRows
    .map((r) => Number(r.dividend_rate))
    .filter((v) => Number.isFinite(v));

  const be = ready?.breakeven;
  const [discountSlider, setDiscountSlider] = useState<number | null>(null);
  const discountActive = discountSlider ?? be?.annual_discount_rate ?? 0.04;
  const liveMonthsToPar = useMemo(() => {
    if (!be) return null;
    return monthsToPriceClient(be.monthly_dividend, discountActive, be.par);
  }, [be, discountActive]);
  const liveMonthsToMkt = useMemo(() => {
    if (!be || sataPx == null) return null;
    return monthsToPriceClient(be.monthly_dividend, discountActive, sataPx);
  }, [be, discountActive, sataPx]);
  const livePvCurve = useMemo(() => {
    if (!be) return [];
    const horizon = Math.max(
      240,
      Math.ceil((liveMonthsToPar ?? 120) * 1.35),
      Math.ceil((liveMonthsToMkt ?? 120) * 1.35)
    );
    return cumulativePvCurveClient(
      be.monthly_dividend,
      discountActive,
      horizon
    );
  }, [be, discountActive, liveMonthsToPar, liveMonthsToMkt]);

  const hedgeStrc = story.hedge?.STRC || initialMarket.mstr?.strc_hedge;
  const hedgeSata = story.hedge?.SATA || initialMarket.asst?.sata_hedge;
  const threeLeg = story.hedge?.strc_three_leg;
  const sataIbit = story.hedge?.sata_ibit;
  // MSTR puts are a poor STRC hedge (basis + IV) — keep in export data,
  // but do not showcase them on the page.
  const isMstrLeg = (leg: string | null | undefined) =>
    String(leg ?? "").toUpperCase().includes("MSTR");
  const strcHedgeLegs = (threeLeg?.legs ?? []).filter(
    (leg) => !isMstrLeg(leg.leg as string)
  );
  const strcHedgeComparison = (threeLeg?.comparison ?? []).filter(
    (row) => !isMstrLeg(row.leg as string)
  );
  const hedgeWinner =
    strcHedgeComparison.length > 0
      ? [...strcHedgeComparison].sort(
          (a, b) => (b.total_yield_10k ?? -Infinity) - (a.total_yield_10k ?? -Infinity)
        )[0]
      : null;
  const sataBook = sataIbit?.book ?? sataIbit?.near_optimal ?? null;
  const sataAssumptions = sataIbit?.assumptions;
  const sataCoc = Number(sataAssumptions?.cost_of_capital ?? 0.0464);
  const sataCapital = Number(
    sataAssumptions?.capital ?? sataIbit?.capital ?? 10_000
  );
  const sataListedStrike =
    sataBook?.strike != null ? Number(sataBook.strike) : null;
  const sataLeveredPct =
    sataBook?.return_pct != null
      ? Number(sataBook.return_pct)
      : sataBook?.total_yield != null && sataCapital > 0
        ? (Number(sataBook.total_yield) / sataCapital) * 100
        : null;
  const sataLeveredPreTax =
    sataBook?.return_pct_pre_tax != null
      ? Number(sataBook.return_pct_pre_tax)
      : sataBook?.total_yield_pre_tax != null && sataCapital > 0
        ? (Number(sataBook.total_yield_pre_tax) / sataCapital) * 100
        : null;

  return (
    <div className="relative mx-auto max-w-6xl px-5 py-14 md:px-8 md:py-16">
      <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
        Preferreds
      </p>
      <h1 className="mt-4 font-display text-4xl text-mist-100 md:text-5xl">
        Bitcoin-backed preferred equities
      </h1>
      <p className="mt-4 text-lg text-mist-300">
        Model fair — NPV of simulated dividend cash flows.
      </p>
      <p className="mt-4 font-mono text-xs text-mist-500">
        {live ? "Live" : "Snapshot"} · {formatTime(asOf)}
        {error ? <span className="text-ember-400"> · {error}</span> : null}
      </p>

      {/* Premium */}
      <section className="mt-12">
        <h2 className="font-display text-3xl text-mist-100">
          Premium to model fair
        </h2>
        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          {premiumRows.map((row) => {
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
                  {premium == null ? "—" : pct(premium)}
                </p>
                <p className="mt-2 font-mono text-xs text-mist-500">
                  mkt {formatUsd(row.market)} · fair {formatUsd(row.fair)}
                </p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Assumptions */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Assumptions</h2>
        <p className="mt-2 text-mist-400">
          Locked inputs for the SATA Monte Carlo. STRC isn&apos;t modeled here
          yet — MSTR&apos;s capital structure has senior debt and multiple
          preferred series competing for the same treasury, which this engine
          doesn&apos;t yet account for.
        </p>
        {ready ? (
          <>
            <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Fact
                label="Simulations"
                value={Number(cfg.num_simulations).toLocaleString()}
              />
              <Fact label="Horizon" value={`${cfg.simulation_years} years`} />
              <Fact
                label="Dividend"
                value={`${(Number(cfg.annual_dividend_rate ?? cfg.sata_annual_dividend_rate) * 100).toFixed(1)}%`}
              />
              <Fact
                label="Monthly coupon"
                value={formatUsd(Number(cfg.monthly_dividend_per_share ?? cfg.sata_monthly_dividend_per_share))}
              />
              <Fact
                label="Bitcoin holdings"
                value={`${Number(cfg.initial_bitcoin_holdings).toLocaleString(undefined, { maximumFractionDigits: 1 })} BTC`}
              />
              <Fact
                label="Cash reserve"
                value={formatCompact(Number(cfg.initial_cash_reserve))}
              />
              <Fact
                label="Flat discount (annual)"
                value={`${(Number(cfg.discount_rate_annual) * 100).toFixed(2)}%`}
              />
              <Fact
                label="Suspension threshold"
                value={`${Number(cfg.dividend_suspension_threshold_multiplier).toFixed(2)}× par`}
              />
              <Fact
                label="BTC spot (run)"
                value={formatUsd(Number(cfg.current_bitcoin_price), 0)}
              />
            </div>
            <div className="mt-6 space-y-3 text-sm text-mist-400">
              <p>
                <span className="text-mist-200">Discount:</span> one flat annual
                rate, compounded monthly into constant discount factors. Set from
                the live Treasury zero curve&apos;s 30-year point (the longest
                published tenor) — a flat rate for the whole horizon, not the
                full curve shape month by month.
              </p>
              <p>
                <span className="text-mist-200">Payment logic:</span> each month,
                pay arrears then the current coupon — cash first, always. Sell
                Bitcoin for any shortfall only when BTC mark-to-market ≥
                threshold × total par (1.00× = sell only while holdings cover
                full par). If the month is not paid in full, the unpaid balance
                compounds (+25 bps/month, capped). Cash is never blocked by the
                threshold.
              </p>
            </div>
          </>
        ) : (
          <p className="mt-6 text-sm text-mist-500">
            SATA valuation results are not available yet.
          </p>
        )}
      </section>

      {/* Bitcoin paths */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Bitcoin paths</h2>
        <p className="mt-2 text-mist-400">
          Monthly Bitcoin returns are drawn from a manually tuned distribution —
          not a Bitcoin price thesis. The knobs below are set so the Monte Carlo
          fair value for SATA lines up with the current market price. Paths below
          start from the baseline spot; fan shows mean, median, and percentiles
          over twenty years.
        </p>
        {story.path_fan ? (
          <div className="mt-8 border border-white/8 bg-ink-900/60 p-5 md:p-6">
            {story.path_fan.distribution ? (
              <div className="mb-6">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Fact
                    label="Ann. mean return"
                    value={
                      story.path_fan.distribution.mean != null
                        ? `${(((1 + Number(story.path_fan.distribution.mean)) ** 12 - 1) * 100).toFixed(1)}%`
                        : "—"
                    }
                  />
                  <Fact
                    label="Ann. vol"
                    value={
                      story.path_fan.distribution.std != null
                        ? `${(Number(story.path_fan.distribution.std) * Math.sqrt(12) * 100).toFixed(0)}%`
                        : "—"
                    }
                  />
                </div>
                <p className="mt-3 font-mono text-[11px] leading-relaxed text-mist-600">
                  Monthly: mean{" "}
                  {story.path_fan.distribution.mean != null
                    ? `${(Number(story.path_fan.distribution.mean) * 100).toFixed(2)}%`
                    : "—"}
                  {" · "}vol{" "}
                  {story.path_fan.distribution.std != null
                    ? `${(Number(story.path_fan.distribution.std) * 100).toFixed(1)}%`
                    : "—"}
                  {" · "}skew{" "}
                  {story.path_fan.distribution.skew != null
                    ? Number(story.path_fan.distribution.skew).toFixed(2)
                    : "—"}
                  {" · "}excess kurtosis{" "}
                  {story.path_fan.distribution.kurtosis != null
                    ? Number(story.path_fan.distribution.kurtosis).toFixed(1)
                    : "—"}
                </p>
                {story.path_fan.historical_distribution ? (
                  <p className="mt-1.5 font-mono text-[11px] leading-relaxed text-mist-600">
                    Historical: mean{" "}
                    {story.path_fan.historical_distribution.mean != null
                      ? `${(Number(story.path_fan.historical_distribution.mean) * 100).toFixed(2)}%`
                      : "—"}
                    {" · "}vol{" "}
                    {story.path_fan.historical_distribution.std != null
                      ? `${(Number(story.path_fan.historical_distribution.std) * 100).toFixed(1)}%`
                      : "—"}
                    {" · "}skew{" "}
                    {story.path_fan.historical_distribution.skew != null
                      ? Number(story.path_fan.historical_distribution.skew).toFixed(2)
                      : "—"}
                    {" · "}excess kurtosis{" "}
                    {story.path_fan.historical_distribution.kurtosis != null
                      ? Number(
                          story.path_fan.historical_distribution.kurtosis,
                        ).toFixed(1)
                      : "—"}
                  </p>
                ) : null}
              </div>
            ) : null}
            <p className="font-mono text-xs text-mist-500">
              {story.path_fan.n_simulations?.toLocaleString()} sims ·{" "}
              {story.path_fan.n_sample_paths} shown · start{" "}
              {formatUsd(story.path_fan.starting_price, 0)} · log scale
            </p>
            <div className="mt-4">
              <BtcPathFanChart fan={story.path_fan} />
            </div>
          </div>
        ) : (
          <p className="mt-6 text-sm text-mist-500">
            Bitcoin path fan is not available yet.
          </p>
        )}
      </section>

      {/* Get even */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Get even</h2>
        <p className="mt-2 text-mist-400">
          Certain monthly coupons, discounted at the rate below, accumulate to
          par after this many months. If Bitcoin keeps funding dividends longer
          than that, NPV beats par; shorter, it does not.
        </p>
        {be ? (
          <div className="mt-8 border border-white/8 bg-ink-900/60 p-5 md:p-6">
            <div className="grid gap-8 md:grid-cols-[minmax(0,14rem)_1fr] md:items-end">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  Months to par
                </p>
                <p className="mt-2 font-mono text-5xl tabular-nums text-ember-400">
                  {liveMonthsToPar ?? "—"}
                </p>
                <p className="mt-3 font-mono text-xs text-mist-500">
                  To market ({formatUsd(sataPx)}): {liveMonthsToMkt ?? "—"} mo
                </p>
              </div>
              <label className="block md:pb-1">
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  Discount rate {(discountActive * 100).toFixed(2)}%
                </span>
                <input
                  type="range"
                  min={0}
                  max={0.08}
                  step={0.001}
                  value={discountActive}
                  onChange={(e) => setDiscountSlider(Number(e.target.value))}
                  className="mt-3 w-full accent-ember-400"
                />
              </label>
            </div>
            <div className="mt-8">
              {livePvCurve.length ? (
                <CumulativePvChart
                  curve={livePvCurve}
                  monthsMarker={liveMonthsToPar}
                  marketMarker={liveMonthsToMkt}
                  priceLine={be.par}
                  priceLabel="Par"
                  marketLine={sataPx}
                  marketLabel="Market"
                />
              ) : (
                <p className="text-sm text-mist-500">Breakeven curve pending.</p>
              )}
            </div>
          </div>
        ) : (
          <p className="mt-6 text-sm text-mist-500">Breakeven data pending.</p>
        )}
      </section>

      {/* Baseline */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Baseline</h2>
        <p className="mt-2 text-mist-400">
          Across simulated Bitcoin paths, dividends only last so long. Trading
          near model fair means the market agrees with that path set — this is
          the market&apos;s implied pessimism, not mine. The return distribution
          was tuned so fair lines up with the live price.
        </p>
        {ready?.baseline ? (
          <>
            <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label="Fair / share" value={formatUsd(ready.baseline.fair_value)} ember />
              <Fact label="vs par" value={pct(ready.baseline.valuation_vs_par)} />
              <Fact
                label="Mean months paid"
                value={
                  ready.baseline.mean_months_paid != null
                    ? ready.baseline.mean_months_paid.toFixed(1)
                    : "—"
                }
              />
              <Fact
                label="Median months paid"
                value={
                  ready.baseline.median_months_paid != null
                    ? ready.baseline.median_months_paid.toFixed(1)
                    : "—"
                }
              />
            </div>
            <div className="mt-8 grid gap-6 lg:grid-cols-2">
              <div className="border border-white/8 bg-ink-900/60 p-5">
                <h3 className="font-display text-lg text-mist-100">
                  Months paid distribution
                </h3>
                {ready.months_paid_histogram ? (
                  <>
                    <div className="mt-4">
                      <DensityHistogramChart
                        binEdges={ready.months_paid_histogram.bin_edges}
                        density={ready.months_paid_histogram.density}
                        mean={ready.months_paid_histogram.mean}
                        median={ready.months_paid_histogram.median}
                        mark={liveMonthsToPar ?? be?.months_to_par ?? null}
                        markLabel="get even"
                        xLabel="months"
                      />
                    </div>
                    {ready.months_paid_histogram.approximate ? (
                      <p className="mt-2 font-mono text-[10px] text-mist-600">
                        Shape sketched from mean / median.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="mt-4 text-sm text-mist-500">
                    Mean {ready.baseline.mean_months_paid?.toFixed(1) ?? "—"} mo · median{" "}
                    {ready.baseline.median_months_paid?.toFixed(1) ?? "—"} mo
                  </p>
                )}
              </div>
              <div className="border border-white/8 bg-ink-900/60 p-5">
                <h3 className="font-display text-lg text-mist-100">NPV distribution</h3>
                {ready.npv_histogram ? (
                  <>
                    <div className="mt-4">
                      <DensityHistogramChart
                        binEdges={ready.npv_histogram.bin_edges}
                        density={ready.npv_histogram.density}
                        mean={ready.npv_histogram.mean}
                        median={ready.npv_histogram.median}
                        mark={sataPx}
                        markLabel="mkt"
                        xLabel="usd"
                      />
                    </div>
                    {ready.npv_histogram.approximate ? (
                      <p className="mt-2 font-mono text-[10px] text-mist-600">
                        Shape sketched from mean / median / std.
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="mt-4 text-sm text-mist-500">
                    Mean {formatUsd(ready.baseline.mean_npv)} · median{" "}
                    {formatUsd(ready.baseline.median_npv)} · σ{" "}
                    {formatUsd(ready.baseline.std_npv)}
                  </p>
                )}
              </div>
            </div>
          </>
        ) : (
          <p className="mt-6 text-sm text-mist-500">Baseline pending.</p>
        )}
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          <div className="border border-white/8 bg-ink-900/40 px-4 py-3 font-mono text-sm text-mist-500">
            STRC: not modeled yet
          </div>
          <div className="border border-white/8 bg-ink-900/40 px-4 py-3 font-mono text-sm text-mist-400">
            SATA mean NPV {formatUsd(ready?.baseline?.mean_npv)} · median{" "}
            {formatUsd(ready?.baseline?.median_npv)}
          </div>
        </div>
      </section>

      {/* If Bitcoin moves */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">If Bitcoin moves</h2>
        <p className="mt-2 text-mist-400">
          Same dividend machine, different opening Bitcoin prices.
        </p>
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <div className="border border-white/8 bg-ink-900/60 p-5">
            <h3 className="font-display text-lg text-mist-100">STRC</h3>
            <p className="mt-6 text-sm text-mist-500">
              Not modeled yet — see the note under Assumptions.
            </p>
          </div>
          <div className="border border-white/8 bg-ink-900/60 p-5">
            <h3 className="font-display text-lg text-mist-100">SATA</h3>
            <div className="mt-4">
              <FairVsBtcChart scenarios={scenarios} highlightBtc={activeBtc} />
            </div>
            {btcStarts.length > 1 ? (
              <label className="mt-6 block">
                <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  BTC start {formatUsd(activeBtc, 0)} → fair{" "}
                  {formatUsd(sliderFair)}
                </span>
                <input
                  type="range"
                  min={btcStarts[0]}
                  max={btcStarts[btcStarts.length - 1]}
                  step={100}
                  value={activeBtc}
                  onChange={(e) => setBtcSlider(Number(e.target.value))}
                  className="mt-2 w-full accent-ember-400"
                />
              </label>
            ) : null}
          </div>
        </div>
      </section>

      {/* Other knobs */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Other knobs</h2>
        <p className="mt-2 text-mist-400">
          Two more assumptions that move fair value without changing the Bitcoin
          path set.
        </p>
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <KnobCard
            title="Suspension threshold"
            caption="BTC mark-to-market must clear this × total par before Bitcoin can be sold for coupons. Cash always pays."
            valueLabel={`${threshX.toFixed(2)}× → ${formatUsd(threshHit?.fair_value as number | null)}`}
            slider={
              <GridSlider
                values={threshValues}
                value={threshX}
                onChange={setThreshSlider}
              />
            }
            chart={
              <SensitivityLineChart
                points={threshRows}
                xKey="threshold_multiplier"
                xTick={(v) => `${v.toFixed(1)}×`}
                highlightX={threshX}
              />
            }
          />
          <KnobCard
            title="Dividend rate"
            caption="Stated coupon on par."
            valueLabel={`${(divX * 100).toFixed(2)}% → ${formatUsd(divHit?.fair_value as number | null)}`}
            slider={
              <GridSlider
                values={divValues}
                value={divX}
                onChange={setDivSlider}
              />
            }
            chart={
              <SensitivityLineChart
                points={divRows}
                xKey="dividend_rate"
                xTick={(v) => `${(v * 100).toFixed(0)}%`}
                highlightX={divX}
              />
            }
          />
        </div>
      </section>

      {/* Hedge */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Hedge the wipeout</h2>
        <p className="mt-2 text-mist-400">
          Wipeout is not Bitcoin at zero — it is a seniority band. Cash covers
          only so many months of coupons; hedge the residual price. For STRC,
          compare direct puts vs IBIT put spreads on a $10k book. SATA hedges
          with IBIT puts sized to the claims / assets strike.
        </p>

        {hedgeStrc ? (
          <div className="mt-8 space-y-8">
            <div className="border border-white/8 bg-ink-900/60 p-5 md:p-6">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                STRC wipeout band
              </p>
              <p className="mt-2 text-sm text-mist-400">
                {String(hedgeStrc.seniors ?? "Converts + STRF")} sit ahead of
                STRC. Fully covered until BTC ≈{" "}
                {formatUsd(Number(hedgeStrc.btc_par), 0)}; wiped by ≈{" "}
                {formatUsd(Number(hedgeStrc.btc_zero), 0)}.
              </p>
              <div className="mt-6">
                <StrcWipeoutBand
                  spot={
                    Number(
                      hedgeStrc.btc_spot ?? story.hedge?.btc_price ?? btc ?? 0
                    ) || null
                  }
                  btcPar={Number(hedgeStrc.btc_par)}
                  btcZero={Number(hedgeStrc.btc_zero)}
                />
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="border border-white/8 bg-ink-900/60 p-5">
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  Hedge amount / share
                </p>
                <p className="mt-2 font-mono text-4xl tabular-nums text-ember-400">
                  {formatUsd(Number(hedgeStrc.hedge_amount_per_share))}
                </p>
                <p className="mt-3 font-mono text-[11px] text-mist-500">
                  {formatUsd(Number(hedgeStrc.strc_price))} −{" "}
                  {formatUsd(Number(hedgeStrc.cash_covered_dividend_per_share))}{" "}
                  cash-covered
                </p>
              </div>
              <div className="border border-white/8 bg-ink-900/60 p-5">
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  Cash covers
                </p>
                <p className="mt-2 font-mono text-4xl tabular-nums text-mist-100">
                  {Number(hedgeStrc.usd_months_dividend_coverage).toFixed(1)}
                  <span className="ml-2 text-lg text-mist-500">mo</span>
                </p>
                <p className="mt-3 font-mono text-[11px] text-mist-500">
                  Leave those coupons unhedged
                </p>
              </div>
            </div>

            <div className="border border-white/8 bg-ink-900/60 p-5 md:p-6">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                Why not MSTR puts
              </p>
              <p className="mt-2 text-sm text-mist-400">
                When Bitcoin crashes hard enough that preferred dividends pause,
                unpaid coupons may still accumulate — but MSTR trades more like
                a call on Bitcoin than a claim that goes to zero. Residual
                optionality means the common is probably still worth something
                in a deep bear market, so you cannot pin a reliable wipeout
                strike. Implied vol is also extreme, so the puts are expensive
                carry for a hedge that may not pay when you need it. Prefer STRC
                puts (same name) or IBIT spreads (BTC-linked wipeout zone).
              </p>
            </div>

            {strcHedgeComparison.length ? (
              <div className="border border-white/8 bg-ink-900/60 p-5 md:p-6">
                <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                  $10k STRC book — puts vs IBIT spreads
                </p>
                <p className="mt-2 text-sm text-mist-400">
                  Best strike per instrument by max total yield (dividend −
                  borrow − theta + tax). Grey = after-tax hedge cost; ember =
                  total yield.
                  {hedgeWinner?.leg
                    ? ` Live winner: ${hedgeWinner.leg} @ ${String(hedgeWinner.best_strike)} → ${formatUsd(hedgeWinner.total_yield_10k, 0)}.`
                    : null}
                </p>
                <div className="mt-6">
                  <HedgeComparisonChart rows={strcHedgeComparison} />
                </div>
                <div className="mt-4 overflow-x-auto">
                  <table className="w-full min-w-[36rem] text-left font-mono text-xs text-mist-400">
                    <thead>
                      <tr className="border-b border-white/10 text-mist-500">
                        <th className="py-2 font-normal">Leg</th>
                        <th className="py-2 font-normal">Expiry</th>
                        <th className="py-2 text-right font-normal">Best</th>
                        <th className="py-2 text-right font-normal">Cost</th>
                        <th className="py-2 text-right font-normal">Yield</th>
                      </tr>
                    </thead>
                    <tbody>
                      {strcHedgeComparison.map((row) => (
                        <tr
                          key={String(row.leg)}
                          className="border-b border-white/5"
                        >
                          <td className="py-2 text-mist-200">{row.leg}</td>
                          <td className="py-2">{row.expirations}</td>
                          <td className="py-2 text-right tabular-nums">
                            {row.best_strike != null
                              ? String(row.best_strike)
                              : "—"}
                          </td>
                          <td className="py-2 text-right tabular-nums">
                            {formatUsd(row.hedge_cost_10k, 0)}
                          </td>
                          <td
                            className={`py-2 text-right tabular-nums ${
                              (row.total_yield_10k ?? 0) >= 0
                                ? "text-ember-400"
                                : "text-mist-500"
                            }`}
                          >
                            {formatUsd(row.total_yield_10k, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}

            <div>
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                Instruments
              </p>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {strcHedgeLegs.map((leg) => (
                  <div
                    key={String(leg.leg)}
                    className="border border-white/8 bg-ink-900/60 p-5"
                  >
                    <p className="font-display text-lg text-mist-100">{leg.leg}</p>
                    <p className="mt-1 font-mono text-xs text-mist-500">
                      {leg.last_expiration ?? "—"}
                      {leg.best?.strike_label
                        ? ` · best ${leg.best.strike_label}`
                        : ""}
                    </p>
                    <dl className="mt-4 space-y-2 font-mono text-xs">
                      <div className="flex justify-between gap-3">
                        <dt className="text-mist-500">Yield / $10k</dt>
                        <dd className="tabular-nums text-ember-400">
                          {formatUsd(leg.best?.total_yield, 0)}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-mist-500">Hedge cost</dt>
                        <dd className="tabular-nums text-mist-200">
                          {formatUsd(leg.best?.hedge_cost_after_tax, 0)}
                        </dd>
                      </div>
                      <div className="flex justify-between gap-3">
                        <dt className="text-mist-500">Mid / contracts</dt>
                        <dd className="tabular-nums text-mist-200">
                          {formatUsd(leg.best?.mid_price)} ·{" "}
                          {leg.best?.contracts_needed != null
                            ? Number(leg.best.contracts_needed).toFixed(2)
                            : "—"}
                        </dd>
                      </div>
                    </dl>
                    {leg.ladder && leg.ladder.length > 0 ? (
                      <ul className="mt-4 space-y-1 border-t border-white/5 pt-3 font-mono text-[10px] text-mist-600">
                        {leg.ladder.slice(0, 5).map((row, i) => (
                          <li
                            key={i}
                            className="flex justify-between gap-2 tabular-nums"
                          >
                            <span>
                              {row.spread != null
                                ? String(row.spread)
                                : `$${row.strike}`}
                            </span>
                            <span>
                              {row.total_yield != null
                                ? formatUsd(Number(row.total_yield), 0)
                                : "—"}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {leg.pnl_series && leg.pnl_series.length > 0 ? (
                      <div className="mt-4">
                        <p className="mb-2 font-mono text-[10px] text-mist-600">
                          Option book P&L vs shock
                        </p>
                        <HedgePnlChart series={leg.pnl_series} />
                      </div>
                    ) : null}
                  </div>
                ))}
                {!strcHedgeLegs.length ? (
                  <>
                    <div className="border border-white/8 bg-ink-900/60 p-5">
                      <p className="font-display text-lg text-mist-100">STRC puts</p>
                      <p className="mt-4 text-sm text-mist-400">
                        Direct hedge near{" "}
                        {formatUsd(Number(hedgeStrc.hedge_amount_per_share))}.
                        Option chain detail is not available yet.
                      </p>
                    </div>
                    <div className="border border-white/8 bg-ink-900/60 p-5">
                      <p className="font-display text-lg text-mist-100">IBIT spreads</p>
                      <p className="mt-4 text-sm text-mist-400">
                        12/4, 12/5, 10/5 near wipeout.
                      </p>
                    </div>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        ) : (
          <p className="mt-6 text-sm text-mist-500">STRC hedge strip unavailable.</p>
        )}

        {/* SATA — IBIT long puts */}
        <div className="mt-12 border border-white/8 bg-ink-900/60 p-5 md:p-6">
          <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
            SATA — IBIT long puts
          </p>
          <p className="mt-2 text-sm text-mist-400">
            Wipeout-aligned put only: continuous optimal = claims / assets ×
            IBIT, then the nearest listed strike. $10k book with margin, borrow,
            theta, and tax.
          </p>

          {hedgeSata || sataIbit ? (
            <>
              <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <Fact
                  label="SATA hedge amount"
                  value={formatUsd(Number(sataIbit?.hedge_amount_per_share))}
                />
                <Fact
                  label="Listed IBIT strike"
                  value={
                    sataListedStrike != null
                      ? formatUsd(sataListedStrike, 0)
                      : "—"
                  }
                  ember
                />
                <Fact
                  label="Levered return (after tax)"
                  value={
                    sataLeveredPct != null
                      ? `${sataLeveredPct >= 0 ? "" : "−"}${Math.abs(sataLeveredPct).toFixed(1)}%`
                      : "—"
                  }
                  ember
                />
              </div>

              <div className="mt-8 grid gap-6 lg:grid-cols-2">
                <div className="overflow-hidden rounded-sm border border-white/8">
                  <p className="border-b border-white/8 bg-ink-950/50 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                    Book assumptions
                  </p>
                  <table className="w-full text-left font-mono text-xs">
                    <tbody className="divide-y divide-white/5">
                      {(
                        [
                          ["Capital", formatUsd(sataCapital, 0)],
                          ["IB margin on SATA", "15%"],
                          ["Cost of capital", `${(sataCoc * 100).toFixed(2)}%`],
                          ["Marginal tax rate", "25%"],
                          [
                            "Continuous optimal",
                            sataIbit?.optimal_strike != null
                              ? formatUsd(Number(sataIbit.optimal_strike), 2)
                              : "—",
                          ],
                          [
                            "Expiry window",
                            sataIbit?.last_expiration
                              ? `${sataIbit.second_last_expiration} → ${sataIbit.last_expiration}`
                              : "—",
                          ],
                          [
                            "Put IV (from mid)",
                            sataBook?.implied_volatility != null
                              ? `${(Number(sataBook.implied_volatility) * 100).toFixed(0)}%`
                              : "—",
                          ],
                        ] as const
                      ).map(([k, v]) => (
                        <tr key={k}>
                          <td className="px-4 py-2 text-mist-500">{k}</td>
                          <td className="px-4 py-2 text-right tabular-nums text-mist-100">
                            {v}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <p className="border-t border-white/5 px-4 py-2 font-mono text-[10px] text-mist-600">
                    15% Interactive Brokers-style margin on SATA. Tax benefit at a
                    flat 25% marginal rate.
                  </p>
                </div>

                <div className="overflow-hidden rounded-sm border border-white/8">
                  <p className="border-b border-white/8 bg-ink-950/50 px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                    $10k book · listed ${sataListedStrike?.toFixed(0) ?? "—"} put
                  </p>
                  {sataBook ? (
                    <table className="w-full text-left font-mono text-xs">
                      <tbody className="divide-y divide-white/5">
                        {(
                          [
                            [
                              "SATA shares long",
                              sataBook.num_shares != null
                                ? Number(sataBook.num_shares).toFixed(1)
                                : "—",
                              false,
                            ],
                            [
                              "IBIT put contracts",
                              sataBook.option_contracts != null
                                ? Number(sataBook.option_contracts).toFixed(2)
                                : "—",
                              false,
                            ],
                            [
                              "Puts / SATA share",
                              sataBook.contracts_needed != null
                                ? Number(sataBook.contracts_needed).toFixed(3)
                                : "—",
                              false,
                            ],
                            [
                              "Put mid",
                              formatUsd(Number(sataBook.mid_price)),
                              false,
                            ],
                            [
                              "Gross purchase",
                              formatUsd(Number(sataBook.total_purchase), 0),
                              false,
                            ],
                            [
                              "Dividend",
                              formatUsd(Number(sataBook.dividend), 0),
                              false,
                            ],
                            [
                              "Theta cost",
                              formatUsd(Number(sataBook.theta_cost), 0),
                              false,
                            ],
                            [
                              "Borrow cost",
                              formatUsd(Number(sataBook.borrow_cost), 0),
                              false,
                            ],
                            [
                              "Tax savings",
                              formatUsd(Number(sataBook.tax_benefit), 0),
                              true,
                            ],
                            [
                              "Return before tax",
                              sataLeveredPreTax != null
                                ? `${sataLeveredPreTax.toFixed(1)}%`
                                : "—",
                              false,
                            ],
                            [
                              "Return after tax",
                              sataLeveredPct != null
                                ? `${sataLeveredPct.toFixed(1)}%`
                                : "—",
                              true,
                            ],
                          ] as const
                        ).map(([k, v, ember]) => (
                          <tr key={k}>
                            <td className="px-4 py-2 text-mist-500">{k}</td>
                            <td
                              className={`px-4 py-2 text-right tabular-nums ${
                                ember ? "text-ember-400" : "text-mist-100"
                              }`}
                            >
                              {v}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p className="px-4 py-4 text-sm text-mist-500">
                      Book detail is not available yet.
                    </p>
                  )}
                </div>
              </div>

              {sataIbit?.pnl_series && sataIbit.pnl_series.length > 0 ? (
                <div className="mt-8">
                  <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
                    Stress — net book vs BTC / IBIT shock
                  </p>
                  <div className="mt-4">
                    <HedgePnlChart series={sataIbit.pnl_series} />
                  </div>
                  <p className="mt-4 text-sm text-mist-400">
                    Parallel spot shocks on the same BTC-start grid as “If Bitcoin
                    moves.”{" "}
                    <span className="text-[#9aabc4]">IBIT puts</span> ·{" "}
                    <span className="text-[#c4a574]">SATA fair Δ</span> (scenario
                    curve × shares) ·{" "}
                    <span className="text-ember-400">net book</span>.
                  </p>
                </div>
              ) : (
                <p className="mt-6 font-mono text-[11px] text-mist-600">
                  Stress curves are not available yet.
                </p>
              )}
            </>
          ) : (
            <p className="mt-4 text-sm text-mist-500">SATA hedge data unavailable.</p>
          )}
        </div>

        {hedgeSata ? (
          <p className="mt-8 font-mono text-[11px] text-mist-600">
            {hedgeSata.btc_zero == null
              ? "Cash often covers enough that BTC alone cannot wipe SATA to zero."
              : `Wiped by ≈ ${formatUsd(Number(hedgeSata.btc_zero), 0)}.`}
            {hedgeSata.btc_full != null
              ? ` Still whole until BTC ≈ ${formatUsd(Number(hedgeSata.btc_full), 0)}.`
              : ""}
          </p>
        ) : null}

        <p className="mt-6">
          <Link
            href="/capital-structure"
            className="font-mono text-xs uppercase tracking-[0.14em] text-ember-400 hover:text-ember-300"
          >
            Full capital stack →
          </Link>
        </p>
      </section>

      {/* Methodology */}
      <section className="mt-16">
        <h2 className="font-display text-3xl text-mist-100">Methodology</h2>
        <ol className="mt-8 space-y-8">
          <li>
            <h3 className="font-display text-xl text-mist-100">
              1. Ask how long certain dividends need to last
            </h3>
            <p className="mt-2 text-mist-400">
              Discount the monthly coupon at the flat annual rate (compounded
              monthly) until NPV equals par or the live market price. That month
              count is the get-even horizon.
            </p>
          </li>
          <li>
            <h3 className="font-display text-xl text-mist-100">
              2. Simulate Bitcoin paths and the dividend machine
            </h3>
            <p className="mt-2 text-mist-400">
              Each month: pay arrears, then the coupon — cash first (always).
              Sell Bitcoin for the shortfall only if holdings mark ≥ threshold ×
              par. Missed amounts compound up to a cap. Average discounted paid
              cash flows across paths is model fair.
            </p>
          </li>
          <li>
            <h3 className="font-display text-xl text-mist-100">
              3. Shock the knobs that matter
            </h3>
            <p className="mt-2 text-mist-400">
              Re-run on grids for Bitcoin starting price, suspension threshold,
              and dividend rate. The site interpolates those precomputed grids —
              it does not re-run Monte Carlo in the browser.
            </p>
          </li>
        </ol>
      </section>

      {/* Disclaimer + roadmap */}
      <section className="mt-20 border border-ember-400/25 bg-ink-900/60 p-6 md:p-8">
        <p className="font-mono text-xs uppercase tracking-[0.28em] text-ember-400">
          Disclaimer
        </p>
        <h2 className="mt-3 font-display text-3xl text-mist-100 md:text-4xl">
          What this model does not do yet
        </h2>
        <p className="mt-4 text-mist-300">
          The numbers above are an immediate-term story under a{" "}
          <span className="text-mist-100">fixed coupon</span> and a{" "}
          <span className="text-mist-100">fixed share count</span>. Real
          preferreds are not that static. Two second-order effects matter a lot —
          and we have not fully modeled them.
        </p>

        <div className="mt-10 space-y-8">
          <div>
            <h3 className="font-display text-xl text-mist-100">
              Interest-rate adjustment mechanism
            </h3>
            <p className="mt-3 text-mist-400">
              Issuers can (and do) reset the stated dividend rate over time —
              often toward a level that keeps the preferred near a target band
              around par. This page assumes the coupon stays where it is for the
              life of the simulation. That is a useful lens for the{" "}
              <span className="text-mist-200">near term</span>: if Bitcoin paths
              and the current machine ran unchanged, what is fair? It is{" "}
              <span className="text-mist-200">not</span> a claim that rates never
              move. Over months and years, adjustments will change cash flows,
              sustainability, and NPV. That feedback loop has to be modeled on
              its own.
            </p>
          </div>

          <div>
            <h3 className="font-display text-xl text-mist-100">
              Issuance and rate response above par
            </h3>
            <p className="mt-3 text-mist-400">
              Model fair can print above $100 — that is not the problem. The
              issue is the{" "}
              <span className="text-mist-200">market price</span>. Around or
              above par, the issuer can sell more shares and/or cut the stated
              rate, so the preferred does not stay rich for long. That supply
              and coupon response is a reflexive second-order effect on{" "}
              <span className="text-mist-200">traded price</span>, not a claim
              that NPV cannot exceed par in the simulation. Ignoring it means
              we are not yet tying model fair back to the offer window the
              issuer actually defends — another piece we intend to add, not
              paper over.
            </p>
          </div>
        </div>

        <div className="mt-12 border-t border-white/10 pt-10">
          <p className="font-mono text-xs uppercase tracking-[0.28em] text-mist-500">
            Roadmap
          </p>
          <h3 className="mt-3 font-display text-2xl text-mist-100">
            What we will model next
          </h3>
          <ol className="mt-6 list-decimal space-y-4 pl-5 text-mist-400">
            <li>
              <span className="text-mist-200">Rate-adjustment policy.</span>{" "}
              Encode how and when the issuer resets the coupon (triggers, step
              size, caps/floors, lag). Run the same Bitcoin paths with an
              endogenous rate path instead of a fixed 13%.
            </li>
            <li>
              <span className="text-mist-200">
                Price impact of those resets.
              </span>{" "}
              When the rate steps up or down, recompute get-even months, cash
              burn, and NPV — and show how fast fair re-centers toward the
              issuer&apos;s target band.
            </li>
            <li>
              <span className="text-mist-200">Issuance / ATM reflexivity.</span>{" "}
              When market price clears a premium threshold near par, add primary
              issuance and/or a coupon cut so the model tracks how the issuer
              defends the offer window — even when simulated NPV still prints
              above $100.
            </li>
            <li>
              <span className="text-mist-200">Joint stress.</span> Combine rate
              resets and issuance with the existing BTC-start and hedge books so
              the site tells one coherent near-term vs long-term story — not two
              silent assumptions.
            </li>
          </ol>
          <p className="mt-8 text-sm text-mist-500">
            Until those land, treat everything on this page as a{" "}
            <span className="text-mist-300">
              fixed-coupon, fixed-share immediate-term valuation
            </span>{" "}
            under stated Bitcoin and payment rules — not a full dynamic capital-
            markets model of the preferred.
          </p>
        </div>
      </section>

      <p className="mt-10">
        <Link href="/commons" className="text-ember-400 hover:underline">
          Compare commons →
        </Link>
      </p>
    </div>
  );
}

function Fact({
  label,
  value,
  ember,
}: {
  label: string;
  value: string;
  ember?: boolean;
}) {
  return (
    <div className="border border-white/8 bg-ink-900/40 px-4 py-3">
      <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
        {label}
      </p>
      <p
        className={`mt-1 font-mono text-lg tabular-nums ${ember ? "text-ember-400" : "text-mist-100"}`}
      >
        {value}
      </p>
    </div>
  );
}

function Row({
  k,
  v,
  ember,
}: {
  k: string;
  v: string;
  ember?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-white/5 pb-2">
      <dt className="text-mist-500">{k}</dt>
      <dd className={`tabular-nums ${ember ? "text-ember-400" : "text-mist-100"}`}>
        {v}
      </dd>
    </div>
  );
}

function KnobCard({
  title,
  caption,
  valueLabel,
  slider,
  chart,
}: {
  title: string;
  caption: string;
  valueLabel: string;
  slider: ReactNode;
  chart: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col border border-white/8 bg-ink-900/60 p-5">
      <h3 className="font-display text-lg text-mist-100">{title}</h3>
      <p className="mt-2 text-sm text-mist-500">{caption}</p>
      <p className="mt-4 font-mono text-xs text-ember-400">{valueLabel}</p>
      {slider}
      <div className="mt-4 flex-1">{chart}</div>
    </div>
  );
}

