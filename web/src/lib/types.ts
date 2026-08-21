export type Instrument = {
  ticker: string;
  name: string;
  issuer: string;
  market_price: number | null;
  kind: string;
  par?: number;
  price_source?: string;
};

export type StrcHedge = {
  strc_price?: number | null;
  monthly_dividend_per_share?: number | null;
  cash_covered_dividend_per_share?: number | null;
  usd_months_dividend_coverage?: number | null;
  hedge_amount_per_share?: number | null;
  btc_spot?: number | null;
  btc_par?: number | null;
  btc_zero?: number | null;
  buffer_to_par_pct?: number | null;
  buffer_to_zero_pct?: number | null;
  seniors?: string | null;
  mstr_price?: number | null;
  mstr_reference_strike?: number | null;
  ibit_price?: number | null;
  ibit_at_par?: number | null;
  ibit_at_zero?: number | null;
  ibit_spreads?: Array<{ long: number; short: number }> | null;
};

export type SataHedge = {
  sata_price?: number | null;
  claim_usd?: number | null;
  btc_full?: number | null;
  btc_zero?: number | null;
  buffer_to_full_pct?: number | null;
  buffer_to_zero_pct?: number | null;
};

export type MarketSnapshot = {
  as_of: string;
  btc_price: number;
  btc?: {
    price: number;
    mstr_holdings?: number;
    mstr_btc_value?: number;
    asst_holdings?: number;
    asst_btc_value?: number;
  };
  instruments: Instrument[];
  mstr: {
    btc_holdings?: number;
    usd_reserve_usd?: number;
    convertible_debt_principal?: number;
    convertible_debt_market_value?: number;
    strf_market_value?: number;
    senior_claims_market_usd?: number;
    senior_claims_face_usd?: number;
    strc_shares?: number;
    source?: string;
    rnav?: {
      rnav_per_share?: number;
      rnav_total?: number;
      rnav_face_total?: number;
      rnav_market_total?: number;
      rnav_face_per_share?: number;
      rnav_market_per_share?: number;
      btc_holdings?: number;
      btc_price?: number;
      btc_value?: number;
      mnav_total?: number;
      cash?: number;
      preferred_market_cap?: number;
      preferred_face_cap?: number;
      preferred_by_series?: Record<string, number>;
      preferred_face_by_series?: Record<string, number>;
      preferreds_total_usd?: number;
      preferreds_face_total_usd?: number;
      preferreds_market_total_usd?: number;
      stre_face_usd?: number;
      stre_shares?: number;
      stre_pricing_note?: string;
      convertible_debt?: number;
      convertible_debt_face?: number;
      convertible_debt_market?: number;
      mstr_shares?: number;
      mstr_market_cap?: number;
      mstr_market_price?: number;
      enterprise_value?: number;
      mnav_multiple?: number | null;
      mnav_description?: string;
      premium_to_rnav_pct?: number | null;
      fair_value_per_share?: number;
      description?: string;
    };
    wipeouts?: Record<string, unknown>;
    strc_hedge?: StrcHedge | null;
  };
  asst: {
    btc_holdings?: number;
    cash?: number;
    sata_shares?: number;
    sata_dividend_rate?: number;
    debt?: number;
    mcap?: number;
    source?: string;
    rnav?: {
      btc_holdings?: number;
      btc_price?: number;
      btc_value?: number;
      cash?: number;
      debt?: number;
      sata_shares?: number;
      sata_face?: number;
      sata_market?: number;
      sata_price?: number | null;
      asst_shares?: number;
      asst_price?: number | null;
      asst_market_cap?: number;
      rnav_face_total?: number;
      rnav_market_total?: number;
      rnav_face_per_share?: number | null;
      rnav_market_per_share?: number | null;
      rnav_total?: number;
      rnav_per_share?: number | null;
      mnav_face?: number | null;
      mnav_market?: number | null;
      premium_face_pct?: number | null;
      premium_market_pct?: number | null;
      fair_value_per_share?: number | null;
    };
    wipeouts?: Record<string, unknown>;
    sata_hedge?: SataHedge | null;
  };
  notes?: Record<string, string>;
};

export type FairTicker = {
  ticker: string;
  market_price: number | null;
  fair_value: number | null;
  gap: number | null;
  gap_pct: number | null;
  source: string;
  fair_label?: string;
  mean_months_paid?: number;
  valuation_vs_par?: number;
  premium_to_rnav_pct?: number | null;
  scenarios?: Array<{
    btc_start_pct?: number;
    btc_start?: number;
    fair_value?: number;
  }>;
  npv_distribution?: {
    mean?: number;
    median?: number;
    std?: number;
    vs_par?: number;
    final_per_share?: number;
  };
  status?: string;
};

export type FairValues = {
  as_of: string;
  tickers: FairTicker[];
  comparison: Array<{
    ticker: string;
    market: number | null;
    fair: number | null;
  }>;
};

export type PreferredHistogram = {
  approximate?: boolean;
  note?: string;
  bin_edges: number[];
  density: number[];
  mean?: number;
  median?: number;
  std?: number;
  min?: number;
  max?: number;
  n?: number;
};

export type PreferredBreakeven = {
  monthly_dividend: number;
  annual_discount_rate: number;
  par: number;
  market_price: number | null;
  months_to_par: number | null;
  months_to_market: number | null;
  pv_curve: Array<{ month: number; pv: number }>;
};

export type PreferredIssuerStory = {
  ticker: string;
  status: string;
  valuation_as_of?: string;
  configuration?: Record<string, number | string | null | undefined>;
  breakeven?: PreferredBreakeven | null;
  baseline?: {
    fair_value?: number | null;
    valuation_vs_par?: number | null;
    mean_months_paid?: number | null;
    median_months_paid?: number | null;
    mean_accumulated_unpaid?: number | null;
    mean_npv?: number | null;
    median_npv?: number | null;
    std_npv?: number | null;
    cv_npv?: number | null;
  } | null;
  npv_histogram?: PreferredHistogram | null;
  months_paid_histogram?: PreferredHistogram | null;
  scenarios?: Array<{
    btc_start_pct?: number | null;
    btc_start?: number | null;
    fair_value?: number | null;
    mean_months_paid?: number | null;
    npv_change_vs_baseline_pct?: number | null;
    elasticity?: number | null;
  }>;
  threshold_sensitivity?: Array<Record<string, number | null | undefined>>;
  dividend_rate_sensitivity?: Array<Record<string, number | null | undefined>>;
};

export type HedgeLegBest = {
  strike_label?: string | null;
  strike?: number | null;
  short_strike?: number | null;
  mid_price?: number | null;
  contracts_needed?: number | null;
  option_contracts?: number | null;
  num_shares?: number | null;
  capital_per_share?: number | null;
  total_purchase?: number | null;
  dividend?: number | null;
  borrow_cost?: number | null;
  theta_cost?: number | null;
  tax_benefit?: number | null;
  total_yield_pre_tax?: number | null;
  hedge_cost_after_tax?: number | null;
  total_yield?: number | null;
  return_pct_pre_tax?: number | null;
  return_pct?: number | null;
  delta?: number | null;
  implied_volatility?: number | null;
};

export type HedgeComparisonRow = {
  leg?: string | null;
  expirations?: string | null;
  strikes?: number | null;
  best_strike?: string | number | null;
  hedge_cost_10k?: number | null;
  total_yield_10k?: number | null;
};

export type HedgeStory = {
  btc_price?: number | null;
  STRC?: StrcHedge | null;
  SATA?: SataHedge | null;
  strc_three_leg?: {
    capital?: number;
    comparison?: HedgeComparisonRow[];
    winner?: HedgeComparisonRow | null;
    ibit_spreads?: Array<{ long: number; short: number }>;
    legs?: Array<{
      leg?: string;
      structure?: string;
      spot?: number | null;
      last_expiration?: string | null;
      wipeout_price?: number | null;
      hedge_reference_strike?: number | null;
      best?: HedgeLegBest | null;
      ladder?: Array<Record<string, number | string | null | undefined>>;
      pnl_series?: Array<{ shock_pct: number; pnl: number }>;
      error?: string;
    }>;
  } | null;
  sata_ibit?: {
    sata_price?: number | null;
    hedge_amount_per_share?: number | null;
    cash_cushion_per_share?: number | null;
    annual_dividend_per_share?: number | null;
    ibit_spot?: number | null;
    optimal_strike?: number | null;
    last_expiration?: string | null;
    second_last_expiration?: string | null;
    capital?: number;
    margin_requirement?: number;
    assumptions?: {
      capital?: number;
      margin_requirement?: number;
      margin_note?: string;
      cost_of_capital?: number;
      marginal_tax_rate?: number;
      contract_multiplier?: number;
    };
    best?: HedgeLegBest | null;
    near_optimal?: HedgeLegBest | null;
    book?: HedgeLegBest | null;
    pnl_series?: Array<{
      shock_pct: number;
      pnl?: number;
      option_pnl?: number;
      preferred_pnl?: number | null;
      preferred_fair?: number | null;
      preferred_extrapolated?: boolean | null;
      net_pnl?: number;
    }>;
    scenario_grid_pct?: number | null;
    zero_btc_fair?: {
      fair_value?: number;
      months_paid?: number;
      accumulated_unpaid_dividends?: number;
    } | null;
    ladder?: Array<Record<string, number | string | null | undefined>>;
    note?: string;
  } | null;
  note?: string;
};

export type PreferredStory = {
  as_of?: string | null;
  order?: string[];
  issuers: Record<string, PreferredIssuerStory>;
  hedge?: HedgeStory;
  path_fan?: {
    scenario_index?: number;
    starting_price?: number;
    months?: number;
    stride?: number;
    n_simulations?: number;
    n_sample_paths?: number;
    month_index: number[];
    mean: number[];
    std?: number[];
    bands?: Record<string, number[]>;
    percentiles: Record<string, number[]>;
    samples: Array<{ id: number; prices: number[] }>;
    distribution?: Record<string, number | null | undefined>;
    historical_distribution?: {
      mean?: number | null;
      std?: number | null;
      skew?: number | null;
      kurtosis?: number | null;
      n_months?: number | null;
      start?: string | null;
      end?: string | null;
    };
    note?: string;
  } | null;
};

/** Site chart payload for the Treasury zero curve used in SATA NPV. */
export type YieldCurveChart = {
  as_of_date?: string | null;
  source?: string | null;
  flat_after_years?: number;
  reference_zero_annual?: number | null;
  max_years?: number;
  pillars: Array<{
    years: number;
    zero_annual: number;
    discount?: number;
  }>;
  curve: Array<{ years: number; zero_annual: number; is_pillar?: boolean }>;
  note?: string;
};

export function formatUsd(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

export function formatCompact(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(n);
}

export function formatTime(iso: string | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function formatShares(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(n);
}

export type DilutionLine = {
  name: string;
  share_count: number;
  include_in_effective_dilution?: boolean;
  notes?: string;
  expiry?: string;
  excluded_reason?: string;
};

export type ShareDilutionIssuer = {
  ticker: string;
  basic_shares?: number;
  effective_diluted_shares?: number;
  gross_diluted_shares?: number;
  rnav_denominator_shares?: number;
  overhang_effective?: number;
  options_outstanding?: number;
  rsu_psu_unvested?: number;
  assumed_diluted_shares_incl_converts?: number;
  convert_preferred_shares_excluded?: number;
  as_of_date?: string;
  title?: string;
  breakdown?: DilutionLine[];
  excluded_from_effective?: DilutionLine[];
  convert_breakdown?: Array<{ name: string; share_count: number }>;
  policy?: string;
  source?: string;
};

export type ShareDilution = {
  as_of?: string;
  notes?: Record<string, string>;
  asst?: ShareDilutionIssuer;
  mstr?: ShareDilutionIssuer;
};
