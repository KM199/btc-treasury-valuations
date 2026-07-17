import {
  formatShares,
  formatTime,
  DilutionLine,
  ShareDilution,
  ShareDilutionIssuer,
} from "@/lib/types";

function Row({
  label,
  value,
  tone = "default",
  indent = false,
  detail,
}: {
  label: string;
  value: string;
  tone?: "default" | "ember" | "muted";
  indent?: boolean;
  detail?: string;
}) {
  const valueClass =
    tone === "ember"
      ? "text-ember-400"
      : tone === "muted"
        ? "text-mist-500"
        : "text-mist-200";
  const labelClass = tone === "muted" ? "text-mist-500" : "text-mist-400";
  return (
    <tr className="border-b border-white/5">
      <td className={`py-2.5 ${indent ? "pl-4" : ""} ${labelClass}`}>
        {label}
        {detail ? (
          <span className="mt-0.5 block text-[10px] text-mist-600">{detail}</span>
        ) : null}
      </td>
      <td className={`py-2.5 text-right font-mono tabular-nums ${valueClass}`}>
        {value}
      </td>
    </tr>
  );
}

function notCountedRows(issuer: ShareDilutionIssuer): DilutionLine[] {
  const excludedExtra = issuer.excluded_from_effective || [];
  const excludedOtM = (issuer.breakdown || []).filter(
    (b) => b.include_in_effective_dilution === false
  );
  const fromData = excludedExtra.length > 0 ? excludedExtra : excludedOtM;
  if (fromData.length > 0) return fromData;

  const convertShares = issuer.convert_preferred_shares_excluded ?? 0;
  if (convertShares > 0) {
    return [
      {
        name: "Converts + STRK",
        share_count: convertShares,
        notes:
          "Strike / conversion too high — stay as debt and preferred claims",
      },
    ];
  }
  return [];
}

function IssuerCard({
  title,
  issuer,
}: {
  title: string;
  issuer: ShareDilutionIssuer;
}) {
  const denom = issuer.rnav_denominator_shares;
  const basic = issuer.basic_shares;
  const included = (issuer.breakdown || []).filter(
    (b) => b.include_in_effective_dilution !== false
  );
  const otm = notCountedRows(issuer);

  return (
    <div className="flex h-full flex-col border border-white/8 bg-ink-900/60 p-5 md:p-6">
      <h3 className="font-display text-xl text-mist-100 md:text-2xl">{title}</h3>

      <div className="mt-6">
        <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-mist-500">
          rNAV share count
        </p>
        <p className="mt-1 font-mono text-3xl tabular-nums text-ember-400 md:text-4xl">
          {formatShares(denom)}
        </p>
        {issuer.as_of_date ? (
          <p className="mt-2 font-mono text-xs text-mist-500">
            As of {issuer.as_of_date}
          </p>
        ) : null}
      </div>

      <table className="mt-8 w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left text-[10px] uppercase tracking-[0.14em] text-mist-500">
            <th className="pb-2 font-normal">Counted</th>
            <th className="pb-2 text-right font-normal">Shares</th>
          </tr>
        </thead>
        <tbody>
          <Row label="Basic" value={formatShares(basic)} />
          {included.map((b) => (
            <Row
              key={b.name}
              label={b.name}
              value={formatShares(b.share_count)}
              indent
            />
          ))}
          <Row label="Total" value={formatShares(denom)} tone="ember" />
        </tbody>
      </table>

      {otm.length > 0 ? (
        <table className="mt-8 w-full font-mono text-sm">
          <thead>
            <tr className="border-b border-white/10 text-left text-[10px] uppercase tracking-[0.14em] text-mist-500">
              <th className="pb-2 font-normal">Not counted</th>
              <th className="pb-2 text-right font-normal">Shares</th>
            </tr>
          </thead>
          <tbody>
            {otm.map((b) => (
              <Row
                key={`otm-${b.name}`}
                label={b.name}
                value={formatShares(b.share_count)}
                tone="muted"
                detail={b.notes || (b.expiry ? `Expire ${b.expiry}` : undefined)}
              />
            ))}
          </tbody>
        </table>
      ) : null}
    </div>
  );
}

export function ShareCountsSection({ dilution }: { dilution: ShareDilution }) {
  if (!dilution.mstr || !dilution.asst) {
    return (
      <p className="text-sm text-mist-500">
        Share dilution data is not available yet.
      </p>
    );
  }

  return (
    <section id="share-counts" className="scroll-mt-24">
      <h2 className="font-display text-3xl text-mist-100">Share counts</h2>
      <p className="mt-2 text-mist-400">
        What sits in the rNAV denominator for each common.
      </p>
      {dilution.as_of ? (
        <p className="mt-3 font-mono text-xs text-mist-500">
          Updated {formatTime(dilution.as_of)}
        </p>
      ) : null}

      <div className="mt-8 grid gap-6 lg:grid-cols-2 lg:items-stretch">
        <IssuerCard title="Strategy (MSTR)" issuer={dilution.mstr} />
        <IssuerCard title="Strive (ASST)" issuer={dilution.asst} />
      </div>
    </section>
  );
}
