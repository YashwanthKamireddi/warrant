import { clockTime, rupees } from "../format";
import type { ChainStatus, LedgerEntry } from "../types";
import { Rows } from "./icons";
import { Badge, Empty, Hash } from "./primitives";

const REFUSALS = new Set(["cart_blocked", "debit_failed", "step_up_declined", "intent_revoked"]);

/** What each entry is, in words.
 *
 *  The column used to print the engine's own event names -- `cart_proposed`,
 *  `step_up_requested` -- which are exactly right in a log and mean nothing to
 *  a person reading the screen for the first time. The engine name is still
 *  there on hover, because for anyone who wants it, it is the thing to grep. */
const SAID: Record<string, string> = {
  intent_issued: "She set the permission",
  cart_proposed: "The agent proposed a basket",
  cart_allowed: "Warrant allowed it",
  cart_blocked: "Warrant refused it",
  step_up_requested: "Warrant asked her to approve",
  step_up_declined: "She declined",
  debit_authorized: "Sent to the payment rail",
  debit_settled: "Paid",
  debit_failed: "The payment failed",
  intent_revoked: "She revoked the permission",
};

/** One line of detail per entry kind, read from the payload the engine wrote.
 *  Nothing here is reconstructed or inferred. */
function detail(entry: LedgerEntry): string {
  const p = entry.payload;
  switch (entry.kind) {
    case "intent_issued":
      return `“${p.intent?.body?.utterance ?? ""}”`;
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
      return `${rupees(p.receipt?.body?.amount_paise ?? 0)} · ${
        p.receipt?.body?.rail?.payment_id ?? ""
      }`;
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
      <Empty icon={<Rows />} title="Nothing recorded yet">
        Approve a permission and the first entry appears here. Every decision is written down,
        including the ones that refuse to spend — a dispute usually turns on what did not happen.
      </Empty>
    );
  }

  const brokenAt = chain?.break?.seq ?? null;

  return (
    <>
      {/* An intact chain used to say nothing at all, which left the tamper
          button with no "before" to destroy. The property is the point: it has
          to be visible while it still holds. */}
      {chain && !chain.break && (
        <div className="notice ok">
          <Badge kind="pass" />
          <span>
            <b>Nothing here has been altered.</b> {entries.length}{" "}
            {entries.length === 1 ? "entry" : "entries"}. Each fingerprint on the
            right is computed from that entry <em>and</em> the one before it, so
            editing any entry changes every fingerprint after it. Latest:{" "}
            <Hash value={chain.head} chars={14} />.
          </span>
        </div>
      )}

      {chain?.break && (
        <div className="notice stop">
          <Badge kind="fail" />
          <span>
            <b>Entry {chain.break.seq} was altered.</b> {chain.break.reason}. Every
            entry from there on no longer adds up. Recomputing the fingerprint found{" "}
            <span className="mono">{chain.break.found.slice(7, 21)}…</span> where the record claims{" "}
            <span className="mono">{chain.break.expected.slice(7, 21)}…</span>.
          </span>
        </div>
      )}

      <div className="ledger">
        <div className="ledger-head">
          <span style={{ textAlign: "right" }}>#</span>
          <span>event</span>
          <span>detail</span>
          <span style={{ textAlign: "right" }}>time</span>
          <span style={{ textAlign: "right" }}>fingerprint</span>
        </div>
        {entries.map((entry) => {
          const refusal = REFUSALS.has(entry.kind);
          const orphaned = brokenAt !== null && entry.seq >= brokenAt;
          return (
            <div
              className={`ledger-row${refusal ? " refusal" : ""}${orphaned ? " orphaned" : ""}`}
              key={entry.seq}
            >
              <span className="ledger-seq">{entry.seq}</span>
              <span className="ledger-kind" title={entry.kind}>
                {SAID[entry.kind] ?? entry.kind}
              </span>
              <span className="ledger-detail" title={detail(entry)}>
                {detail(entry)}
              </span>
              <span className="ledger-time">{clockTime(entry.recorded_at)}</span>
              <span className="ledger-hash">
                <Hash value={entry.hash} />
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}
