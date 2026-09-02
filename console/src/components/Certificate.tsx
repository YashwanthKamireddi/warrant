import { relativeWindow, rupees } from "../format";
import type { PendingIntent, Scope, Signature } from "../types";
import { Seal } from "./primitives";

const PROVENANCE: Record<PendingIntent["source"], string> = {
  pinned:
    "Scope pinned, so this run is identical on every machine. Start a session with " +
    "derive to interpret the sentence live instead.",
  live: "Interpreted by a live model call.",
  transcript: "Replayed from the bundled transcript. No live call was made.",
  fallback: "No model was reachable, so the scope narrowed to the deterministic minimum.",
};

const PROVENANCE_LABEL: Record<PendingIntent["source"], string> = {
  pinned: "Scope pinned",
  live: "Interpreted live",
  transcript: "Interpretation replayed",
  fallback: "No model",
};

interface Props {
  pending: PendingIntent;
  scope: Scope | null;
  signature: Signature | null;
  justSigned: boolean;
}

/** The permission, presented as the instrument it is: a grant, its terms, and a
 *  seal. Everything a person is agreeing to is on one face of the document. */
export function Certificate({ pending, scope, signature, justSigned }: Props) {
  const s = scope ?? pending.scope;

  return (
    <div className="certificate">
      <div className="certificate-grant">
        <p>{pending.approval_prompt}</p>
        <Seal keyId={signature?.key_id ?? null} stamping={justSigned} />
      </div>

      {/* A person approving a spend needs three answers: how much, where, how
          long. The remaining terms are real and enforced, but they are the
          engine's business until someone asks. */}
      <dl className="terms">
        <div className="term">
          <dt>How much</dt>
          <dd>{rupees(s.max_total_paise, { compact: true })}</dd>
        </div>
        <div className="term">
          <dt>Where</dt>
          <dd>{s.merchants.join(", ")}</dd>
        </div>
        <div className="term">
          <dt>How long</dt>
          <dd>{relativeWindow(s.not_before, s.expires_at)}</dd>
        </div>
      </dl>

      <details className="terms-more">
        <summary>Every term the gate enforces</summary>
        <dl className="terms">
          <div className="term">
            <dt>Per order</dt>
            <dd>{rupees(s.max_per_txn_paise, { compact: true })}</dd>
          </div>
          <div className="term">
            <dt>Orders permitted</dt>
            <dd>{s.max_txns}</dd>
          </div>
          <div className="term">
            <dt>Categories</dt>
            <dd>{s.categories.join(", ")}</dd>
          </div>
          {s.step_up_over_paise !== null && (
            <div className="term">
              <dt>Second signature over</dt>
              <dd>{rupees(s.step_up_over_paise, { compact: true })}</dd>
            </div>
          )}
          <div className="term">
            <dt>Signed by</dt>
            <dd className="mono" style={{ fontSize: 12 }}>
              {signature?.key_id ?? "not yet signed"}
            </dd>
          </div>
        </dl>
      </details>

      {pending.narrowed_by_envelope && (
        <p className="certificate-note">
          <b>Narrowed by the envelope.</b> The interpretation proposed{" "}
          {rupees(pending.proposed_max_total_paise, { compact: true })}; the merchant's configured
          ceiling allows {rupees(s.max_total_paise, { compact: true })}. The narrower of the two
          wins, always.
        </p>
      )}

      {pending.ambiguities.length > 0 && (
        <p className="certificate-note caution">
          <span aria-hidden>!</span>
          <span>{pending.ambiguities.join("; ")}</span>
        </p>
      )}

      <p className="certificate-note">
        <b>{PROVENANCE_LABEL[pending.source]}.</b> {PROVENANCE[pending.source]}
      </p>
    </div>
  );
}
