import { useState } from "react";
import { shortHash } from "../format";

/** The only ornament in the product. A seal means one thing: a key signed this.
 *  It carries the last four of the key id, so two different signers are visibly
 *  different rather than both being "signed". */
export function Seal({ keyId, stamping }: { keyId: string | null; stamping?: boolean }) {
  if (!keyId) {
    return (
      <div className="seal" style={{ opacity: 0.28 }} aria-label="not yet signed">
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

/** Hashes are long and mostly noise, but the full value has to be reachable --
 *  a reviewer verifying the chain needs to copy it, not squint at it. */
export function Hash({ value, chars = 10 }: { value: string; chars?: number }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="copy"
      title={value}
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 1100);
      }}
    >
      {copied ? "copied" : `${shortHash(value, chars)}…`}
    </button>
  );
}

export function Meter({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const tone = pct >= 100 ? "over" : pct >= 90 ? "near" : "";
  return (
    <div className="meter" role="presentation">
      <i className={tone} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      <span>{children}</span>
    </div>
  );
}
