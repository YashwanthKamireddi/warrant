import { useState } from "react";
import { rupees, shortHash } from "../format";

/** The single ornament in the product. A seal means one thing — a key signed
 *  this — so it carries four characters of that key id. Two different signers
 *  are visibly different rather than both being "signed". */
export function Seal({ keyId, stamping }: { keyId: string | null; stamping?: boolean }) {
  if (!keyId) {
    return (
      <div className="seal unsigned" aria-label="Not yet signed" title="Not yet signed">
        <span>—</span>
      </div>
    );
  }
  return (
    <div
      className={`seal${stamping ? " stamping" : ""}`}
      title={`Signed by ${keyId}`}
      aria-label={`Signed by ${keyId}`}
    >
      <span>{keyId.replace("key_", "").slice(0, 4).toUpperCase()}</span>
    </div>
  );
}

/** Hashes are long and mostly noise, but the full value must stay reachable —
 *  anyone verifying the chain needs to copy it, not squint at it. */
export function Hash({ value, chars = 8 }: { value: string; chars?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className={`hash${copied ? " copied" : ""}`}
      title={`${value} — click to copy`}
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      }}
    >
      {copied ? "copied" : shortHash(value, chars)}
    </button>
  );
}

/** A spend gauge. Turns amber near the ceiling and red at it, because the
 *  distance to a hard bound is the number an operator actually watches. */
export function Gauge({
  label,
  used,
  total,
  unit = "money",
}: {
  label: string;
  used: number;
  total: number;
  unit?: "money" | "count";
}) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const tone = pct >= 100 ? "full" : pct >= 85 ? "warn" : "";
  const fmt = (v: number) => (unit === "money" ? rupees(v, { compact: true }) : String(v));
  return (
    <div className="gauge">
      <div className="gauge-top">
        <span className="gauge-label">{label}</span>
        <span className="gauge-value">
          {fmt(used)} <em>/ {fmt(total)}</em>
        </span>
      </div>
      <div
        className="track"
        role="meter"
        aria-valuenow={used}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-label={label}
      >
        <i className={tone} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Badge({ kind }: { kind: "pass" | "warn" | "fail" }) {
  const glyph = kind === "pass" ? "✓" : kind === "warn" ? "!" : "✕";
  return (
    <span className={`badge ${kind}`} aria-hidden>
      {glyph}
    </span>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-mark">{icon}</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}


/** Who the viewer is at this point in the flow.
 *
 * The console asks one person to be three: the customer who grants permission,
 * the agent that spends it, and the risk team that reads the aftermath. Saying
 * so is the difference between a storefront that looks like a checkout and one
 * that reads as "you are the agent now, try something".
 */
export function Role({
  as,
  name,
  hint,
}: {
  as: "customer" | "agent" | "merchant";
  name: string;
  hint?: string;
}) {
  const initial = { customer: "P", agent: "AI", merchant: "RT" }[as];
  return (
    <div className="role">
      <span className={`role-glyph ${as}`} aria-hidden>
        {initial}
      </span>
      <span className="role-name">
        You are <b>{name}</b>
      </span>
      {hint && <span className="role-hint">{hint}</span>}
    </div>
  );
}
