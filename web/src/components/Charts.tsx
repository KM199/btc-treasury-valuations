"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatUsd } from "@/lib/types";

type Row = { ticker: string; market: number | null; fair: number | null };

export function MarketVsFairChart({ rows }: { rows: Row[] }) {
  const data = rows
    .filter((r) => r.market != null || r.fair != null)
    .map((r) => ({
      ticker: r.ticker,
      Market: r.market ?? undefined,
      "Model fair": r.fair ?? undefined,
    }));

  if (!data.length) {
    return (
      <p className="text-sm text-mist-500">
        Fair values appear after the daily valuation job runs.
      </p>
    );
  }

  return (
    <div className="h-72 w-full md:h-80">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barGap={6} barCategoryGap="28%">
          <CartesianGrid stroke="rgba(232,238,248,0.06)" vertical={false} />
          <XAxis
            dataKey="ticker"
            tick={{ fill: "#9aabc4", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
          />
          <Tooltip
            cursor={{ fill: "rgba(232,238,248,0.04)" }}
            contentStyle={{
              background: "#121826",
              border: "1px solid rgba(232,238,248,0.08)",
              borderRadius: 8,
            }}
            formatter={(value: number) => formatUsd(value)}
          />
          <Legend wrapperStyle={{ color: "#9aabc4", fontSize: 12 }} />
          <Bar dataKey="Market" fill="#9aabc4" radius={[4, 4, 0, 0]} maxBarSize={36} />
          <Bar
            dataKey="Model fair"
            fill="#e8893a"
            radius={[4, 4, 0, 0]}
            maxBarSize={36}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ScenarioElasticityChart({
  scenarios,
}: {
  scenarios: Array<{
    btc_start_pct?: number;
    btc_start?: number;
    fair_value?: number;
  }>;
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

  if (data.length < 2) return null;

  const xMin = Math.floor(data[0].btcPrice / 10_000) * 10_000;
  const xMax = Math.ceil(data[data.length - 1].btcPrice / 10_000) * 10_000;
  const ticks: number[] = [];
  for (let t = xMin; t <= xMax; t += 10_000) {
    ticks.push(t);
  }

  // Baseline (0% shock) for a vertical guide, if present
  const baseline = data.find((d) => d.btcStartPct === 0);

  return (
    <div className="h-72 w-full md:h-80">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 8, bottom: 24 }}>
          <CartesianGrid stroke="rgba(232,238,248,0.06)" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="btcPrice"
            domain={[xMin, xMax]}
            ticks={ticks}
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `$${Math.round(v / 1000)}k`}
            label={{
              value: "Bitcoin starting price",
              position: "insideBottom",
              offset: -10,
              fill: "#6b7c96",
              fontSize: 11,
            }}
          />
          <YAxis
            type="number"
            tick={{ fill: "#9aabc4", fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => `$${v}`}
            width={52}
          />
          {baseline ? (
            <ReferenceLine
              x={baseline.btcPrice}
              stroke="rgba(232,238,248,0.2)"
              strokeDasharray="4 4"
            />
          ) : null}
          <Tooltip
            contentStyle={{
              background: "#121826",
              border: "1px solid rgba(232,238,248,0.08)",
              borderRadius: 8,
            }}
            // Use payload so we can show BTC $, clean %, and fair value
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
                <div className="rounded-md border border-white/10 bg-ink-800 px-3 py-2 text-sm text-mist-100 shadow-lg">
                  <p className="font-mono text-mist-300">
                    BTC {formatUsd(row.btcPrice, 0)}
                    <span className="text-mist-500"> · {pct} vs today</span>
                  </p>
                  <p className="mt-1 font-mono text-ember-400">
                    Fair value {formatUsd(row.fair)}
                  </p>
                </div>
              );
            }}
          />
          <Line
            type="monotone"
            dataKey="fair"
            name="Fair value"
            stroke="#e8893a"
            strokeWidth={2}
            dot={{ r: 3.5, fill: "#e8893a", stroke: "#0c1018", strokeWidth: 1.5 }}
            activeDot={{ r: 5, fill: "#f0a46a", stroke: "#0c1018", strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

