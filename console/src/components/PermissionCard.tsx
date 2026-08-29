import { rupees, relativeWindow } from "../format";
import type { PendingIntent, Scope, Signature } from "../types";
import { Seal } from "./primitives";

const SOURCE_COPY: Record<PendingIntent["source"], { label: string; note: string }> = {
  live: { label: "live model", note: "Interpreted by a live model call." },
  transcript: {
    label: "replayed",
    note: "Replayed from the bundled transcript. No live call was made.",
  },
  fallback: {
    label: "no model",
    note: "No model was available, so the scope narrowed to the deterministic minimum.",
  },
};

interface Props {
  pending: PendingIntent | null;
  scope: Scope | null;
  signature: Signature | null;
  justSigned: boolean;
}

export function PermissionCard({ pending, scope, signature, justSigned }: Props) {
  const s = scope ?? pending?.scope;
  if (!s || !pending) return null;

  const source = SOURCE_COPY[pending.source];

  return (
    <div className="permission">
      <div className="permission-head">
        <p className="permission-text">{pending.approval_prompt}</p>
        <Seal keyId={signature?.key_id ?? null} stamping={justSigned} />
      </div>

      <dl className="bounds">
        <div className="bound">
          <dt>total</dt>
          <dd>{rupees(s.max_total_paise, { compact: true })}</dd>
        </div>
        <div className="bound">
          <dt>per order</dt>
          <dd>{rupees(s.max_per_txn_paise, { compact: true })}</dd>
        </div>
        <div className="bound">
          <dt>orders</dt>
          <dd>{s.max_txns}</dd>
        </div>
        <div className="bound">
          <dt>expires in</dt>
          <dd>{relativeWindow(s.not_before, s.expires_at)}</dd>
        </div>
        <div className="bound">
          <dt>merchants</dt>
          <dd>{s.merchants.join(", ")}</dd>
        </div>
        <div className="bound">
          <dt>categories</dt>
          <dd>{s.categories.join(", ")}</dd>
        </div>
      </dl>

      {pending.narrowed_by_envelope && (
        <p className="narrowed">
          The envelope tightened this. The interpretation proposed{" "}
          <b>{rupees(pending.proposed_max_total_paise, { compact: true })}</b>; the merchant's
          configured ceiling allows <b>{rupees(s.max_total_paise, { compact: true })}</b>. The
          narrower of the two wins, always.
        </p>
      )}

      {pending.ambiguities.length > 0 && (
        <div className="ambiguity">
          <span aria-hidden>!</span>
          <span>{pending.ambiguities.join("; ")}</span>
        </div>
      )}

      <p className="narrowed" style={{ borderTop: "1px solid var(--hairline)" }}>
        <b>{source.label}</b> — {source.note}
      </p>
    </div>
  );
}
