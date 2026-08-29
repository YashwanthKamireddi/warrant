import { rupees } from "../format";
import type { EvidencePack } from "../types";
import { Doc } from "./icons";
import { Badge, Empty } from "./primitives";

const FIELDS: { key: keyof EvidencePack; title: string; note: string }[] = [
  {
    key: "explanation_letter",
    title: "explanation_letter",
    note: "assembled from ledger entries · 1,000 character limit",
  },
  {
    key: "customer_communication",
    title: "customer_communication",
    note: "the instruction, and the permission they approved",
  },
  { key: "proof_of_service", title: "proof_of_service", note: "what was delivered" },
];

export function EvidenceView({
  pack,
  error,
}: {
  pack: EvidencePack | null;
  error: string | null;
}) {
  if (error || !pack) {
    return (
      <Empty icon={<Doc />} title="No settled payment yet">
        The evidence pack is assembled from a settled debit. Authorise a basket that clears every
        check and the full dispute submission appears here.
      </Empty>
    );
  }

  const verified = pack.signatures_verified && pack.chain_intact;

  return (
    <>
      <div className={`notice ${verified ? "ok" : "stop"}`}>
        <Badge kind={verified ? "pass" : "fail"} />
        <span>{pack.verification_note}</span>
      </div>

      <p className="evidence-intro">
        An agent-initiated payment has no device fingerprint, no session and no click. This is what
        a merchant sends the bank instead: the exact words the cardholder said, the bounded
        permission they approved, the basket checked against it, and the signatures binding all
        three to payment <span className="mono">{pack.payment_id}</span> for{" "}
        {rupees(pack.amount_paise)}. The bank verifies it against the cardholder's public key
        without trusting the merchant's records.
      </p>

      {FIELDS.map((field) => (
        <section className="doc" key={field.key}>
          <div className="doc-head">
            <h4>{field.title}</h4>
            <small>{field.note}</small>
          </div>
          <pre>{String(pack[field.key])}</pre>
        </section>
      ))}

      <section className="doc">
        <div className="doc-head">
          <h4>access_activity_log</h4>
          <small>machine-readable · independently verifiable</small>
        </div>
        <pre>{JSON.stringify(pack.access_activity_log, null, 2)}</pre>
      </section>
    </>
  );
}
