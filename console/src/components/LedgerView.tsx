import { clockTime, rupees } from "../format";
import type { ChainStatus, LedgerEntry } from "../types";
import { Empty, Hash } from "./primitives";

const REFUSALS = new Set(["cart_blocked", "debit_failed", "step_up_declined", "intent_revoked"]);

/** One line of human-readable detail per entry kind, drawn from the payload the
 *  engine actually wrote. Nothing here is reconstructed or guessed. */
function detail(entry: LedgerEntry): string {
  const p = entry.payload;
  switch (entry.kind) {
    case "intent_issued":
      return `"${p.intent?.body?.utterance ?? ""}"`;
    case "cart_proposed":
      return `${rupees(p.cart?.body?.total_paise ?? 0)} at ${p.cart?.body?.merchant ?? "?"}`;
    case "cart_allowed":
      return `${rupees(p.cart?.body?.total_paise ?? 0)} · every binding check passed`;
    case "cart_blocked":
    case "step_up_requested":
      return (p.reasons ?? []).join(" · ") || (p.failed_rules ?? []).join(", ");
    case "debit_authorized":
      return `placed on rail · ${p.rail?.ref?.order_id ?? ""}`;
    case "debit_settled":
      return `${rupees(p.receipt?.body?.amount_paise ?? 0)} · ${p.receipt?.body?.rail?.payment_id ?? ""}`;
    case "debit_failed":
      return [p.rail?.error_source, p.rail?.error_step, p.rail?.error_reason]
        .filter(Boolean)
        .join(" / ");
    case "intent_revoked":
      return String(p.reason ?? "");
    default:
      return "";
  }
}

export function LedgerView({
  entries,
  chain,
}: {
  entries: LedgerEntry[];
  chain: ChainStatus | null;
}) {
  if (entries.length === 0) {
    return (
      <Empty title="Nothing recorded yet">
        Approve a permission and the first entry appears here. Every decision is written down,
        including the ones that refuse to spend.
      </Empty>
    );
  }

  const brokenAt = chain?.break?.seq ?? null;

  return (
    <>
      <div className="ledger">
        {entries.map((entry) => {
          const refusal = REFUSALS.has(entry.kind);
          const broken = brokenAt !== null && entry.seq >= brokenAt;
          return (
            <div
              className={`ledger-row${refusal ? " refusal" : ""}${broken ? " broken" : ""}`}
              key={entry.seq}
            >
              <span className="ledger-seq">{entry.seq}</span>
              <span className={`ledger-kind${refusal ? " refusal" : ""}`}>{entry.kind}</span>
              <span className="ledger-detail" title={detail(entry)}>
                {detail(entry)}
              </span>
              <span className="ledger-hash">
                {clockTime(entry.recorded_at)} <Hash value={entry.hash} chars={8} />
              </span>
            </div>
          );
        })}
      </div>

      {chain?.break && (
        <div className="verify-banner bad" style={{ marginTop: 14 }}>
          <span aria-hidden>×</span>
          <span>
            <b>Chain broken at entry {chain.break.seq}</b> — {chain.break.reason}. Every entry from
            there on is orphaned. Recomputing the hashes found{" "}
            <code>{chain.break.found.slice(7, 19)}…</code> where the record claims{" "}
            <code>{chain.break.expected.slice(7, 19)}…</code>.
          </span>
        </div>
      )}
    </>
  );
}
