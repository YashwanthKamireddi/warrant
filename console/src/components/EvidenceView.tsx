import { rupees } from "../format";
import type { EvidencePack } from "../types";
import { Empty } from "./primitives";

const FIELDS: { key: keyof EvidencePack; title: string; note: string }[] = [
  {
    key: "explanation_letter",
    title: "explanation_letter",
    note: "assembled from ledger entries · 1,000 char limit",
  },
  {
    key: "customer_communication",
    title: "customer_communication",
    note: "the instruction and the approval given",
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
  if (error) {
    return (
      <Empty title="No settled payment yet">
        The evidence pack is built from a settled debit. Authorise a basket that clears every check
        and it becomes available here.
      </Empty>
    );
  }
  if (!pack) return null;

  const ok = pack.signatures_verified && pack.chain_intact;

  return (
    <div className="evidence">
      <div className={`verify-banner ${ok ? "ok" : "bad"}`}>
        <span aria-hidden>{ok ? "✓" : "×"}</span>
        <span>{pack.verification_note}</span>
      </div>

      <p style={{ margin: 0, color: "var(--text-muted)", fontSize: 12.5, lineHeight: 1.55 }}>
        An agent-initiated payment has no device fingerprint, no session and no click. This is what
        a merchant sends the bank instead: the exact words the cardholder said, the bounded
        permission they approved, the basket checked against it, and the signatures binding all
        three to payment <code>{pack.payment_id}</code> for {rupees(pack.amount_paise)}. The bank
        can verify it against the cardholder's public key without trusting the merchant's records.
      </p>

      {FIELDS.map((field) => (
        <section className="evidence-field" key={field.key}>
          <header>
            <h4>{field.title}</h4>
            <small>{field.note}</small>
          </header>
          <pre>{String(pack[field.key])}</pre>
        </section>
      ))}

      <section className="evidence-field">
        <header>
          <h4>access_activity_log</h4>
          <small>machine-readable · independently verifiable</small>
        </header>
        <pre>{JSON.stringify(pack.access_activity_log, null, 2)}</pre>
      </section>
    </div>
  );
}
