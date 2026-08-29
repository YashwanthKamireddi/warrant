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

export function DecisionCard({ outcome, index }: { outcome: Outcome; index: number }) {
  const [open, setOpen] = useState(outcome.verdict !== "allow");
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
          </span>
        </span>
        <span className="decision-amount">{rupees(outcome.cart.total_paise)}</span>
      </button>

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
            <div className="teaches">
              Placed on the rail as <span className="mono">{outcome.rail.ref.order_id}</span>,
              awaiting payment.{" "}
              {typeof outcome.rail.raw.payment_link === "string" && (
                <a href={outcome.rail.raw.payment_link} target="_blank" rel="noreferrer">
                  Open the payment link
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
