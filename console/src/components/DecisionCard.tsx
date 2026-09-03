import { useState } from "react";
import { rupees } from "../format";
import type { Check, Outcome } from "../types";
import { Chevron } from "./icons";
import { Badge, Hash } from "./primitives";

/** Numeric bounds are paise; string bounds are allowlists and ids. */
function bound(value: number | string): string {
  if (typeof value === "number") {
    return value > 1000 ? rupees(value, { compact: true }) : String(value);
  }
  return value.length > 20 ? `${value.slice(0, 18)}…` : value;
}

function Checks({ checks }: { checks: Check[] }) {
  const [showPassing, setShowPassing] = useState(false);
  const failed = checks.filter((c) => c.status === "fail");
  const warned = checks.filter((c) => c.status === "warn");
  const passed = checks.filter((c) => c.status === "pass");
  const shown = showPassing ? checks : [...failed, ...warned];

  return (
    <>
      <div className="checks-bar">
        <span>
          {checks.length} checks · {failed.length} failed · {warned.length} advisory
        </span>
        <button className="btn btn-ghost btn-sm" onClick={() => setShowPassing((v) => !v)}>
          {showPassing ? "Hide passing" : `Show ${passed.length} passing`}
        </button>
      </div>
      <div className="checks">
        {shown.map((check) => (
          <div className={`check ${check.status}`} key={check.rule}>
            <Badge kind={check.status} />
            <span className="rule">{check.rule}</span>
            <span className="detail">{check.detail}</span>
            <span className="limit">
              {check.observed !== null && check.limit !== null && (
                <span>
                  {bound(check.observed)} / {bound(check.limit)}
                </span>
              )}
              {!check.binding && <em className="tag-advisory">advisory</em>}
            </span>
          </div>
        ))}
      </div>
    </>
  );
}

export function DecisionCard({
  outcome,
  index,
  realOrder,
  onPlaceOnRazorpay,
  busy = false,
}: {
  outcome: Outcome;
  index: number;
  /** The real Razorpay order this decision produced, once somebody asked for one. */
  realOrder?: { order_id: string | null; payment_link: string | null };
  /** Absent when there are no Razorpay keys, or the debit never settled. */
  onPlaceOnRazorpay?: () => void;
  busy?: boolean;
}) {
  // Allowed baskets collapse, because a clean pass has nothing to read. The one
  // exception is a debit placed on a real rail but not yet settled: the payment
  // link is the only actionable thing on the page and must not sit behind a click.
  const awaitingPayment = Boolean(
    outcome.rail && outcome.rail.ok && !outcome.rail.settled,
  );
  const [open, setOpen] = useState(outcome.verdict !== "allow" || awaitingPayment);
  const failed = outcome.checks.filter((c) => c.status === "fail").length;

  return (
    <article className={`decision ${outcome.verdict}`}>
      <button className="decision-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={`chev${open ? " open" : ""}`}>
          <Chevron />
        </span>
        <span className={`verdict ${outcome.verdict}`}>{outcome.verdict.toUpperCase()}</span>
        <span className="decision-id">
          <b>{outcome.cart.line_items.map((i) => `${i.name} ×${i.qty}`).join(", ")}</b>
          <span className="decision-meta">
            <span>#{index + 1}</span>
            <span className="mono">{outcome.cart.id}</span>
            <span>{outcome.cart.merchant}</span>
            <span>
              {outcome.checks.length} checks{failed > 0 ? `, ${failed} failed` : ""}
            </span>
            <span>{outcome.model_used ? "model consulted" : "no model call"}</span>
            {outcome.elapsed_us !== undefined && (
              <span
                title={
                  outcome.rail_kind === "razorpay"
                    ? "Includes the Razorpay network round trip"
                    : "Gate, ledger and simulated rail, in process"
                }
              >
                {outcome.elapsed_us < 1000
                  ? `${Math.round(outcome.elapsed_us)}µs`
                  : `${(outcome.elapsed_us / 1000).toFixed(1)}ms`}
              </span>
            )}
          </span>
        </span>
        <span className="decision-amount">{rupees(outcome.cart.total_paise)}</span>
      </button>


      {/* The walkthrough settles on the simulator so the record completes.
          This is the same signed cart, placed on the real rail, which is
          what produces an order id and a link somebody can actually open.
          Nothing is re-decided: the gate allowed this basket already. */}
      {onPlaceOnRazorpay && !realOrder && (
        <div className="real-rail">
          <button className="btn btn-sm" onClick={onPlaceOnRazorpay} disabled={busy}>
            {busy ? "Placing…" : "Place this on real Razorpay"}
          </button>
          <span>Creates a real Order and Payment Link in test mode.</span>
        </div>
      )}

      {realOrder && (
        <div className="real-rail placed">
          <span className="placed-head">
            <Badge kind="pass" />
            <b>On Razorpay</b>
            <span className="mono">{realOrder.order_id}</span>
          </span>
          {realOrder.payment_link && (
            <a
              className="btn btn-sm"
              href={realOrder.payment_link}
              target="_blank"
              rel="noreferrer"
            >
              Open the real checkout ↗
            </a>
          )}
        </div>
      )}

      {open && (
        <div className="decision-body">
          {outcome.reasons.length > 0 && (
            <div className="why">
              {outcome.reasons.map((reason, i) => (
                <p className="why-item" key={i}>
                  <Badge kind={outcome.verdict === "block" ? "fail" : "warn"} />
                  <span>{reason}</span>
                </p>
              ))}
            </div>
          )}

          <Checks checks={outcome.checks} />

          {outcome.receipt && (
            <div className="settled">
              <Badge kind="pass" />
              <span>Settled</span>
              <span className="mono">{outcome.receipt.id}</span>
              <span className="mono">
                {outcome.rail?.ref.payment_id ?? outcome.rail?.ref.order_id}
              </span>
              <Hash value={outcome.cart.digest} />
            </div>
          )}

          {outcome.rail && outcome.rail.ok && !outcome.rail.settled && (
            <div className="placed">
              <span className="placed-head">
                <Badge kind="pass" />
                <b>Placed on the rail</b>
                <span className="mono">{outcome.rail.ref.order_id}</span>
              </span>
              <p>
                Reported as <code>settled=false</code>. A payment cannot be completed
                server to server — the customer authorises on their own device, which is
                the property that makes the rail trustworthy.
              </p>
              {typeof outcome.rail.raw.payment_link === "string" && (
                <a
                  className="btn btn-secondary btn-sm"
                  href={outcome.rail.raw.payment_link}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open the real payment link ↗
                </a>
              )}
            </div>
          )}


          {outcome.rail && !outcome.rail.ok && (
            <div className="teaches" style={{ color: "var(--stop)" }}>
              Rail failed — {outcome.rail.error_source} / {outcome.rail.error_step} /{" "}
              {outcome.rail.error_reason}
            </div>
          )}

          {outcome.label && <p className="teaches">{outcome.label}</p>}
        </div>
      )}
    </article>
  );
}
