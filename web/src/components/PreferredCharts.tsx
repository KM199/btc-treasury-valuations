"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatUsd } from "@/lib/types";

const tipStyle = {
  background: "#121826",
  border: "1px solid rgba(232,238,248,0.08)",
  borderRadius: 8,
};

export function CumulativePvChart({
  curve,
  monthsMarker,
  marketMarker,
  priceLine,
  priceLabel,
  marketLine,
  marketLabel,
}: {
  curve: Array<{ month: number; pv: number }>;
  monthsMarker: number | null;
  marketMarker?: number | null;
  priceLine: number | null;
  priceLabel: string;
  marketLine?: number | null;
  marketLabel?: string;
}) {
  if (!curve.length) {
    return <p className="text-sm text-mist-500">No PV curve.</p>;
  }
  const maxMonth = curve[curve.length - 1]?.month ?? 0;
  const yearTicks = Array.from(
    { length: Math.floor(maxMonth / 12) + 1 },
    (_, i) => i * 12
  ).filter((m) => m > 0 && m <= maxMonth);

  return (
    <div className="h-64 w-full md:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={curve} margin={{ top: 8, right: 12, left: 4, bottom: 20 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            dataKey="month"
            ticks={yearTicks.length ? yearTicks : undefined}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => {
              const years = v / 12;
              return years === Math.floor(years) ? `${v}m · ${years}y` : `${v}m`;
            }}
            height={36}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
            width={48}
          />
          {priceLine != null ? (
            <ReferenceLine
              y={priceLine}
              stroke="rgba(232,137,58,0.55)"
              strokeDasharray="4 4"
              label={{
                value: priceLabel,
                fill: "#e8893a",
                fontSize: 11,
                position: "insideTopRight",
              }}
            />
          ) : null}
          {marketLine != null ? (
            <ReferenceLine
              y={marketLine}
              stroke="rgba(154,171,196,0.45)"
              strokeDasharray="3 3"
              label={{
                value: marketLabel ?? "Market",
                fill: "#9aabc4",
                fontSize: 11,
                position: "insideTopLeft",
              }}
            />
          ) : null}
          {monthsMarker != null ? (
            <ReferenceLine
              x={monthsMarker}
              stroke="#e8893a"
              strokeWidth={1.5}
            />
          ) : null}
          {marketMarker != null && marketMarker !== monthsMarker ? (
            <ReferenceLine
              x={marketMarker}
              stroke="#9aabc4"
              strokeDasharray="4 4"
            />
          ) : null}
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number) => formatUsd(v)}
            labelFormatter={(m) => {
              const months = Number(m);
              const years = months / 12;
              return months % 12 === 0
                ? `Month ${months} · Year ${years}`
                : `Month ${months} · ${years.toFixed(1)}y`;
            }}
          />
          <Area
            type="monotone"
            dataKey="pv"
            name="Cumulative PV"
            stroke="#e8893a"
            fill="rgba(232,137,58,0.18)"
            strokeWidth={2}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DensityHistogramChart({
  binEdges,
  density,
  mean,
  median,
  mark,
  markLabel,
  xLabel,
}: {
  binEdges: number[];
  density: number[];
  mean?: number | null;
  median?: number | null;
  mark?: number | null;
  markLabel?: string;
  xLabel: string;
}) {
  const data = density.map((d, i) => {
    const lo = binEdges[i];
    const hi = binEdges[i + 1];
    return {
      mid: (lo + hi) / 2,
      density: d,
      label: formatUsd(lo, 0),
    };
  });
  if (data.length < 2) {
    return <p className="text-sm text-mist-500">No distribution.</p>;
  }
  return (
    <div className="h-56 w-full md:h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" vertical={false} />
          <XAxis
            dataKey="mid"
            tick={{ fill: "#9aabc4", fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) =>
              xLabel === "months" ? `${Math.round(v)}` : `$${Math.round(v)}`
            }
          />
          <YAxis hide />
          {mean != null ? (
            <ReferenceLine x={mean} stroke="#e8893a" strokeDasharray="3 3" />
          ) : null}
          {median != null ? (
            <ReferenceLine x={median} stroke="#9aabc4" strokeDasharray="3 3" />
          ) : null}
          {mark != null ? (
            <ReferenceLine
              x={mark}
              stroke="#7dcea0"
              strokeWidth={2}
              label={{
                value: markLabel ?? "mark",
                fill: "#7dcea0",
                fontSize: 10,
                position: "insideTopLeft",
              }}
            />
          ) : null}
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number) => v.toFixed(4)}
            labelFormatter={(_, payload) => {
              const row = payload?.[0]?.payload as { mid?: number } | undefined;
              if (!row?.mid) return "";
              return xLabel === "months"
                ? `${Math.round(row.mid)} months`
                : formatUsd(row.mid);
            }}
          />
          <Bar dataKey="density" fill="rgba(232,137,58,0.55)" radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FairVsBtcChart({
  scenarios,
  highlightBtc,
  capLevel = 100,
}: {
  scenarios: Array<{
    btc_start?: number | null;
    btc_start_pct?: number | null;
    fair_value?: number | null;
  }>;
  highlightBtc?: number | null;
  capLevel?: number | null;
}) {
  const data = scenarios
    .filter((s) => s.fair_value != null && s.btc_start != null)
    .map((s) => {
      const raw = s.btc_start_pct ?? 0;
      const pct = Math.abs(raw) <= 2 ? raw * 100 : raw;
      return {
        btcPrice: s.btc_start as number,
        btcStartPct: Math.round(pct),
        fair: s.fair_value as number,
      };
    })
    .sort((a, b) => a.btcPrice - b.btcPrice);

  if (data.length < 2) {
    return <p className="text-sm text-mist-500">Scenario curve pending.</p>;
  }

  const baseline = data.find((d) => d.btcStartPct === 0);

  // Model NPV keeps climbing with Bitcoin; the traded price does not. Above the
  // $100 stated amount the issuer can sell shares at the market into the
  // premium and step the coupon down, both of which pull the quote back to par
  // — so the tradeable price flattens where the curve crosses the ceiling.
  // Find that crossing and run a dotted line from there to the right edge.
  const cap = capLevel != null && Number.isFinite(capLevel) ? capLevel : null;
  const maxBtc = data[data.length - 1].btcPrice;
  let capStartBtc: number | null = null;
  if (cap != null && data.some((d) => d.fair > cap)) {
    capStartBtc = data[0].fair >= cap ? data[0].btcPrice : null;
    for (let i = 1; capStartBtc == null && i < data.length; i += 1) {
      const prev = data[i - 1];
      const cur = data[i];
      if (prev.fair < cap && cur.fair >= cap) {
        const t = (cap - prev.fair) / (cur.fair - prev.fair);
        capStartBtc = prev.btcPrice + t * (cur.btcPrice - prev.btcPrice);
      }
    }
  }

  return (
    <div className="h-64 w-full md:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 20 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="btcPrice"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
            width={48}
          />
          {baseline ? (
            <ReferenceLine
              x={baseline.btcPrice}
              stroke="rgba(232,238,248,0.2)"
              strokeDasharray="4 4"
            />
          ) : null}
          {cap != null && capStartBtc != null ? (
            <ReferenceLine
              segment={[
                { x: capStartBtc, y: cap },
                { x: maxBtc, y: cap },
              ]}
              stroke="#c1cdde"
              strokeWidth={1.75}
              strokeDasharray="1 5"
              strokeLinecap="round"
              ifOverflow="extendDomain"
              label={{
                value: `Traded ceiling \u2248 $${cap}`,
                fill: "#c1cdde",
                fontSize: 11,
                position: "insideBottomRight",
              }}
            />
          ) : null}
          {cap != null && capStartBtc != null ? (
            <ReferenceDot
              x={capStartBtc}
              y={cap}
              r={3.5}
              fill="#c1cdde"
              stroke="#0c1018"
              strokeWidth={1}
              isFront
            />
          ) : null}
          {highlightBtc != null ? (
            <ReferenceLine x={highlightBtc} stroke="#7dcea0" strokeWidth={1.5} />
          ) : null}
          <Tooltip
            contentStyle={tipStyle}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const row = payload[0].payload as {
                btcPrice: number;
                btcStartPct: number;
                fair: number;
              };
              const pct =
                row.btcStartPct > 0
                  ? `+${row.btcStartPct}%`
                  : `${row.btcStartPct}%`;
              return (
                <div className="px-3 py-2 font-mono text-sm text-mist-100">
                  <p className="text-mist-300">
                    BTC {formatUsd(row.btcPrice, 0)}
                    <span className="text-mist-500"> · {pct}</span>
                  </p>
                  <p className="mt-1 text-ember-400">Fair {formatUsd(row.fair)}</p>
                  {cap != null && row.fair > cap ? (
                    <p className="mt-1 text-[11px] text-mist-500">
                      Model only — above the ${cap} ceiling
                    </p>
                  ) : null}
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="fair"
            stroke="#e8893a"
            strokeWidth={2}
            dot={{ r: 3, fill: "#e8893a", stroke: "#0c1018", strokeWidth: 1 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SensitivityLineChart({
  points,
  xKey,
  xTick,
  highlightX,
}: {
  points: Array<Record<string, number | null | undefined>>;
  xKey: string;
  xTick: (v: number) => string;
  highlightX?: number | null;
}) {
  const data = points
    .filter((p) => p[xKey] != null && p.fair_value != null)
    .map((p) => ({
      x: Number(p[xKey]),
      fair: Number(p.fair_value),
      months: p.mean_months_paid != null ? Number(p.mean_months_paid) : null,
    }))
    .sort((a, b) => a.x - b.x);

  if (data.length < 2) {
    return <p className="text-sm text-mist-500">No sensitivity series.</p>;
  }

  return (
    <div className="h-52 w-full md:h-56">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="x"
            domain={["dataMin", "dataMax"]}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={xTick}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
            width={48}
          />
          {highlightX != null ? (
            <ReferenceLine x={highlightX} stroke="#7dcea0" strokeDasharray="4 4" />
          ) : null}
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number) => formatUsd(v)}
            labelFormatter={(v) => xTick(Number(v))}
          />
          <Line
            type="monotone"
            dataKey="fair"
            stroke="#e8893a"
            strokeWidth={2}
            dot={{ r: 3, fill: "#e8893a" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function formatTenorYears(years: number): string {
  if (years < 1) {
    const months = Math.round(years * 12);
    return `${months}m`;
  }
  if (Number.isInteger(years) || Math.abs(years - Math.round(years)) < 1e-9) {
    return `${Math.round(years)}y`;
  }
  return `${years.toFixed(1)}y`;
}

export function YieldCurveChart({
  curve,
}: {
  curve: {
    as_of_date?: string | null;
    flat_after_years?: number;
    reference_zero_annual?: number | null;
    pillars?: Array<{ years: number; zero_annual: number }>;
    curve: Array<{ years: number; zero_annual: number; is_pillar?: boolean }>;
  };
}) {
  const data = (curve.curve ?? []).map((p) => ({
    years: p.years,
    zeroPct: p.zero_annual * 100,
    isPillar: Boolean(p.is_pillar),
  }));

  if (data.length < 2) {
    return <p className="text-sm text-mist-500">No yield curve.</p>;
  }

  const flatAfter = curve.flat_after_years ?? 30;
  const refPct =
    curve.reference_zero_annual != null
      ? curve.reference_zero_annual * 100
      : null;
  const maxYears = data[data.length - 1]?.years ?? 40;
  const xTicks = [1 / 12, 1, 2, 5, 10, 20, 30, 40].filter(
    (t) => t <= maxYears + 1e-9
  );
  const yVals = data.map((d) => d.zeroPct);
  const yMin = Math.floor(Math.min(...yVals) * 10) / 10 - 0.1;
  const yMax = Math.ceil(Math.max(...yVals) * 10) / 10 + 0.1;

  return (
    <div className="h-56 w-full md:h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 12, right: 16, left: 4, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="years"
            domain={["dataMin", "dataMax"]}
            ticks={xTicks}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => formatTenorYears(v)}
          />
          <YAxis
            domain={[yMin, yMax]}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v.toFixed(1)}%`}
            width={48}
          />
          <ReferenceLine
            x={flatAfter}
            stroke="rgba(125,206,160,0.45)"
            strokeDasharray="4 4"
            label={{
              value: "flat →",
              fill: "#7dcea0",
              fontSize: 11,
              position: "insideTopLeft",
            }}
          />
          {refPct != null ? (
            <ReferenceLine
              y={refPct}
              stroke="rgba(232,137,58,0.35)"
              strokeDasharray="3 3"
            />
          ) : null}
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number) => [`${v.toFixed(2)}%`, "Zero"]}
            labelFormatter={(v) => formatTenorYears(Number(v))}
          />
          <Line
            type="monotone"
            dataKey="zeroPct"
            stroke="#7dcea0"
            strokeWidth={2}
            dot={(props: {
              cx?: number;
              cy?: number;
              payload?: { isPillar?: boolean };
            }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null || !payload?.isPillar) {
                return <g key={`empty-${cx ?? 0}-${cy ?? 0}`} />;
              }
              return (
                <circle
                  key={`pillar-${cx}-${cy}`}
                  cx={cx}
                  cy={cy}
                  r={3.5}
                  fill="#e8893a"
                  stroke="#121826"
                  strokeWidth={1}
                />
              );
            }}
            isAnimationActive={false}
            name="Zero rate"
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function BtcPathFanChart({
  fan,
}: {
  fan: {
    month_index: number[];
    mean: number[];
    percentiles: Record<string, number[]>;
    bands?: Record<string, number[]>;
    samples: Array<{ id: number; prices: number[] }>;
    starting_price?: number;
  };
}) {
  // Percentiles — not mean±σ in dollar space (right-skewed prices make
  // mean−2σ go negative / hit a $1 floor while real p5 stays far higher).
  const seriesKeys = ["p5", "p25", "p75", "p95", "median", "mean"] as const;

  const labels: Record<(typeof seriesKeys)[number], string> = {
    p5: "5th pct",
    p25: "25th pct",
    p75: "75th pct",
    p95: "95th pct",
    median: "Median",
    mean: "Mean",
  };

  const colors: Record<(typeof seriesKeys)[number], string> = {
    p5: "#6b7c96",
    p25: "#9aabc4",
    p75: "#c4a574",
    p95: "#a67c52",
    median: "#b8c5d6",
    mean: "#e8893a",
  };

  const data = fan.month_index.map((month, i) => {
    const row: Record<string, number | undefined> = {
      month,
      mean: fan.mean[i],
      median: fan.percentiles.p50?.[i],
      p5: fan.percentiles.p5?.[i],
      p25: fan.percentiles.p25?.[i],
      p75: fan.percentiles.p75?.[i],
      p95: fan.percentiles.p95?.[i],
    };
    for (const s of fan.samples) {
      row[`s${s.id}`] = s.prices[i];
    }
    return row;
  });

  if (data.length < 2) {
    return <p className="text-sm text-mist-500">No path fan data.</p>;
  }

  const yearTicks = fan.month_index.filter((m) => {
    if (m === 0) return true;
    const step = fan.month_index.length > 150 ? 24 : 12;
    return m % step === 0;
  });

  return (
    <div>
      <div className="h-72 w-full md:h-96">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 28 }}>
            <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
            <XAxis
              dataKey="month"
              ticks={yearTicks}
              tick={{ fill: "#9aabc4", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v: number) => {
                if (v === 0) return "0";
                const years = v / 12;
                return years === Math.floor(years)
                  ? `${v}m · ${years}y`
                  : `${v}m`;
              }}
              interval={0}
              height={36}
            />
            <YAxis
              scale="log"
              domain={["auto", "auto"]}
              tick={{ fill: "#9aabc4", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickFormatter={(v) =>
                v >= 1_000_000
                  ? `$${Math.round(v / 1_000_000)}M`
                  : v >= 1000
                    ? `$${Math.round(v / 1000)}k`
                    : `$${v}`
              }
              width={52}
            />
            {fan.starting_price != null ? (
              <ReferenceLine
                y={fan.starting_price}
                stroke="rgba(125,206,160,0.45)"
                strokeDasharray="4 4"
              />
            ) : null}
            <Tooltip
              contentStyle={tipStyle}
              content={({ active, label, payload }) => {
                if (!active || !payload?.length) return null;
                const months = Number(label);
                const years = months / 12;
                const title =
                  months % 12 === 0 && years >= 1
                    ? `Month ${months} · Year ${years}`
                    : `Month ${months} · ${years.toFixed(1)}y`;
                const rows = payload.filter((p) => {
                  const k = String(p.dataKey ?? "");
                  return seriesKeys.includes(k as (typeof seriesKeys)[number]);
                });
                if (!rows.length) return null;
                return (
                  <div className="rounded-md border border-white/10 bg-ink-800 px-3 py-2 font-mono text-sm shadow-lg">
                    <p className="text-mist-400">{title}</p>
                    <ul className="mt-2 space-y-1">
                      {rows.map((p) => {
                        const k = String(p.dataKey) as (typeof seriesKeys)[number];
                        return (
                          <li key={k} style={{ color: colors[k] }}>
                            {labels[k]} {formatUsd(Number(p.value), 0)}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              }}
            />
            {fan.samples.map((s) => (
              <Line
                key={s.id}
                type="monotone"
                dataKey={`s${s.id}`}
                stroke="rgba(154,171,196,0.16)"
                strokeWidth={1}
                dot={false}
                isAnimationActive={false}
                legendType="none"
                tooltipType="none"
              />
            ))}
            {(
              ["p5", "p95", "p25", "p75", "median", "mean"] as const
            ).map((key) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={colors[key]}
                strokeWidth={key === "mean" ? 2.5 : key === "median" ? 2 : 1.5}
                strokeDasharray={
                  key === "p5" || key === "p95"
                    ? "5 4"
                    : key === "p25" || key === "p75"
                      ? "3 3"
                      : undefined
                }
                dot={false}
                isAnimationActive={false}
                name={key}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="mt-5 flex flex-wrap gap-x-5 gap-y-2.5 text-xs text-mist-400">
        <li className="inline-flex items-center gap-2">
          <span
            className="inline-block h-0.5 w-5 rounded"
            style={{ background: "rgba(154,171,196,0.55)" }}
          />
          Sample paths
        </li>
        {seriesKeys.map((key) => (
          <li key={key} className="inline-flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-5 rounded"
              style={{ background: colors[key] }}
            />
            <span style={{ color: colors[key] }}>{labels[key]}</span>
          </li>
        ))}
        {fan.starting_price != null ? (
          <li className="inline-flex items-center gap-2">
            <span
              className="inline-block h-0.5 w-5"
              style={{
                borderTop: "1.5px dashed rgba(125,206,160,0.7)",
              }}
            />
            <span className="text-mint-400">Start price</span>
          </li>
        ) : null}
      </ul>
    </div>
  );
}

/** $10k book: after-tax hedge cost vs total yield by instrument. */
export function HedgeComparisonChart({
  rows,
}: {
  rows: Array<{
    leg?: string | null;
    hedge_cost_10k?: number | null;
    total_yield_10k?: number | null;
  }>;
}) {
  const data = rows
    .filter((r) => r.leg)
    .map((r) => ({
      name: String(r.leg)
        .replace(" put spreads", "")
        .replace(" puts", ""),
      cost: r.hedge_cost_10k ?? null,
      yield: r.total_yield_10k ?? null,
    }));
  if (!data.length) {
    return <p className="text-sm text-mist-500">No three-leg comparison yet.</p>;
  }
  return (
    <div className="h-64 w-full md:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            dataKey="name"
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${Math.round(v / 1000)}k`}
            width={44}
          />
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number, name: string) => [
              formatUsd(v, 0),
              name === "cost" ? "Hedge cost" : "Total yield",
            ]}
          />
          <ReferenceLine y={0} stroke="rgba(232,238,248,0.2)" />
          <Bar dataKey="cost" name="cost" fill="#6b7c96" radius={[3, 3, 0, 0]} maxBarSize={36} />
          <Bar dataKey="yield" name="yield" fill="#e8893a" radius={[3, 3, 0, 0]} maxBarSize={36} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** SATA $10k book total yield across IBIT put strikes. */
export function SataYieldByStrikeChart({
  rows,
  optimalStrike,
}: {
  rows: Array<{ strike: number; total_yield: number }>;
  optimalStrike?: number | null;
}) {
  if (!rows.length) {
    return <p className="text-sm text-mist-500">No SATA strike ladder yet.</p>;
  }
  return (
    <div className="h-64 w-full md:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 12, left: 4, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            dataKey="strike"
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${Math.round(v / 1000)}k`}
            width={44}
          />
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number) => [formatUsd(v, 0), "Total yield"]}
            labelFormatter={(s) => `IBIT put $${s}`}
          />
          <ReferenceLine y={0} stroke="rgba(232,238,248,0.2)" />
          {optimalStrike != null ? (
            <ReferenceLine
              x={Math.round(optimalStrike / 5) * 5}
              stroke="#7dcea0"
              strokeDasharray="4 4"
            />
          ) : null}
          <Bar
            dataKey="total_yield"
            fill="#e8893a"
            radius={[3, 3, 0, 0]}
            maxBarSize={28}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Option + preferred book P&L vs underlying / BTC shock. */
export function HedgePnlChart({
  series,
}: {
  series: Array<{
    shock_pct: number;
    pnl?: number;
    option_pnl?: number;
    preferred_pnl?: number | null;
    net_pnl?: number;
  }>;
}) {
  if (!series.length) return null;
  const span = Math.max(...series.map((r) => Math.abs(r.shock_pct)));
  const bound = Math.ceil(span / 25) * 25;
  const hasPreferred = series.some(
    (r) => r.preferred_pnl != null && Number.isFinite(r.preferred_pnl)
  );
  const data = series.map((r) => ({
    shock_pct: r.shock_pct,
    option: r.option_pnl ?? r.pnl ?? 0,
    preferred: r.preferred_pnl ?? null,
    net: r.net_pnl ?? r.pnl ?? 0,
  }));
  return (
    <div className="h-64 w-full md:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 22, left: 4, bottom: 8 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            dataKey="shock_pct"
            type="number"
            domain={[-bound, bound]}
            ticks={[-bound, -bound / 2, 0, bound / 2, bound]}
            interval={0}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${Math.round(v / 1000)}k`}
            width={44}
          />
          <Tooltip
            contentStyle={tipStyle}
            formatter={(v: number, name: string) => [
              formatUsd(v, 0),
              name === "option"
                ? "IBIT puts"
                : name === "preferred"
                  ? "SATA fair"
                  : "Net book",
            ]}
            labelFormatter={(s) => `BTC / IBIT ${Number(s) > 0 ? "+" : ""}${s}%`}
          />
          <ReferenceLine y={0} stroke="rgba(232,238,248,0.25)" />
          <Line
            type="monotone"
            dataKey="option"
            stroke="#9aabc4"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
          />
          {hasPreferred ? (
            <Line
              type="monotone"
              dataKey="preferred"
              stroke="#c4a574"
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              isAnimationActive={false}
            />
          ) : null}
          <Line
            type="monotone"
            dataKey="net"
            stroke="#e8893a"
            strokeWidth={2.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-1 font-mono text-[10px] text-mist-500">
        <li className="inline-flex items-center gap-2">
          <span className="inline-block h-0.5 w-4 bg-[#9aabc4]" />
          IBIT puts
        </li>
        {hasPreferred ? (
          <li className="inline-flex items-center gap-2">
            <span className="inline-block h-0.5 w-4 bg-[#c4a574]" />
            SATA fair
          </li>
        ) : null}
        <li className="inline-flex items-center gap-2">
          <span className="inline-block h-0.5 w-4 bg-ember-400" />
          Net book
        </li>
      </ul>
    </div>
  );
}

/** Horizontal BTC scale: spot → band start (par) → band end (zero). */
export function StrcWipeoutBand({
  spot,
  btcPar,
  btcZero,
}: {
  spot: number | null | undefined;
  btcPar: number | null | undefined;
  btcZero: number | null | undefined;
}) {
  if (
    spot == null ||
    btcPar == null ||
    btcZero == null ||
    !(spot > 0) ||
    !(btcPar > 0) ||
    !(btcZero >= 0)
  ) {
    return null;
  }
  const lo = Math.min(btcZero * 0.85, btcPar * 0.7);
  const hi = spot * 1.02;
  const span = hi - lo;
  const pctPos = (v: number) =>
    Math.min(100, Math.max(0, ((v - lo) / span) * 100));
  const fallToPar = ((spot - btcPar) / spot) * 100;
  const fallToZero = ((spot - btcZero) / spot) * 100;

  return (
    <div>
      <div className="relative h-3 w-full rounded-sm bg-ink-800">
        <div
          className="absolute inset-y-0 rounded-sm bg-gradient-to-r from-ember-500/70 via-ember-400/35 to-mint-400/40"
          style={{
            left: `${pctPos(btcZero)}%`,
            width: `${pctPos(spot) - pctPos(btcZero)}%`,
          }}
        />
        {(
          [
            { v: btcZero, label: "Zero", color: "#e8893a" },
            { v: btcPar, label: "Par", color: "#c4a574" },
            { v: spot, label: "Spot", color: "#7dcea0" },
          ] as const
        ).map((m) => (
          <div
            key={m.label}
            className="absolute top-1/2 h-5 w-0.5 -translate-y-1/2"
            style={{ left: `${pctPos(m.v)}%`, background: m.color }}
            title={`${m.label} ${formatUsd(m.v, 0)}`}
          />
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 font-mono text-[11px] text-mist-500">
        <span>
          <span className="text-mint-400">Spot</span> {formatUsd(spot, 0)}
        </span>
        <span>
          <span className="text-[#c4a574]">Band starts</span> {formatUsd(btcPar, 0)}
          {" · "}
          {fallToPar.toFixed(0)}% BTC drop
        </span>
        <span>
          <span className="text-ember-400">Wiped</span> {formatUsd(btcZero, 0)}
          {" · "}
          {fallToZero.toFixed(0)}% BTC drop
        </span>
      </div>
    </div>
  );
}
