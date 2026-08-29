import { relativeWindow, rupees } from "../format";
import type { PendingIntent, Scope, Signature } from "../types";
import { Seal } from "./primitives";

const PROVENANCE: Record<PendingIntent["source"], string> = {
  live: "Interpreted by a live model call.",
  transcript: "Replayed from the bundled transcript. No live call was made.",
  fallback: "No model was reachable, so the scope narrowed to the deterministic minimum.",
};

const PROVENANCE_LABEL: Record<PendingIntent["source"], string> = {
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

      <dl className="terms">
        <div className="term">
          <dt>Total ceiling</dt>
          <dd>{rupees(s.max_total_paise, { compact: true })}</dd>
        </div>
        <div className="term">
          <dt>Per order</dt>
          <dd>{rupees(s.max_per_txn_paise, { compact: true })}</dd>
        </div>
        <div className="term">
          <dt>Orders permitted</dt>
          <dd>{s.max_txns}</dd>
        </div>
        <div className="term">
          <dt>Expires in</dt>
          <dd>{relativeWindow(s.not_before, s.expires_at)}</dd>
        </div>
        <div className="term">
          <dt>Merchants</dt>
          <dd>{s.merchants.join(", ")}</dd>
        </div>
        <div className="term">
          <dt>Categories</dt>
          <dd>{s.categories.join(", ")}</dd>
        </div>
        {s.step_up_over_paise !== null && (
          <>
            <div className="term">
              <dt>Co-signature over</dt>
              <dd>{rupees(s.step_up_over_paise, { compact: true })}</dd>
            </div>
            <div className="term">
              <dt>Signed by</dt>
              <dd className="mono" style={{ fontSize: 12 }}>
                {signature?.key_id ?? "unsigned"}
              </dd>
            </div>
          </>
        )}
      </dl>

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
