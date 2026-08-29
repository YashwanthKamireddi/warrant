import { useState } from "react";
import { rupees } from "../format";
import type { Check, Outcome } from "../types";
import { Hash } from "./primitives";

const GLYPH: Record<Check["status"], string> = { pass: "·", warn: "!", fail: "×" };

function ChecksTable({ checks }: { checks: Check[] }) {
  const [showPassing, setShowPassing] = useState(false);
  const failed = checks.filter((c) => c.status === "fail");
  const warned = checks.filter((c) => c.status === "warn");
  const passed = checks.filter((c) => c.status === "pass");
  const shown = showPassing ? checks : [...failed, ...warned];

  return (
    <div className="checks">
      <div className="checks-head">
        <span>
          {checks.length} checks · {failed.length} failed · {warned.length} warned
        </span>
        <button className="copy" onClick={() => setShowPassing((v) => !v)}>
          {showPassing ? "hide passing" : `show ${passed.length} passing`}
        </button>
      </div>
      {shown.map((check) => (
        <div className={`check ${check.status}`} key={check.rule}>
          <span className="glyph" aria-hidden>
            {GLYPH[check.status]}
          </span>
          <span className="rule">{check.rule}</span>
          <span className="detail">{check.detail}</span>
          <span className="bound">
            {check.observed !== null && check.limit !== null ? (
              <>
                {formatBound(check.observed)} / {formatBound(check.limit)}
              </>
            ) : null}
            {!check.binding && <em className="advisory">advisory</em>}
          </span>
        </div>
      ))}
    </div>
  );
}

/** Numeric bounds are paise; string bounds are allowlists and ids. */
function formatBound(value: number | string): string {
  if (typeof value === "number") {
    return value > 1000 ? rupees(value, { compact: true }) : String(value);
  }
  return value.length > 22 ? `${value.slice(0, 20)}…` : value;
}

export function DecisionCard({ outcome, index }: { outcome: Outcome; index: number }) {
  const [open, setOpen] = useState(outcome.verdict !== "allow");
  const failed = outcome.checks.filter((c) => c.status === "fail").length;

  return (
    <article className={`decision ${outcome.verdict}`}>
      <button className="decision-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={`chevron${open ? " open" : ""}`} aria-hidden>
          ▶
        </span>
        <span className={`verdict ${outcome.verdict}`}>{outcome.verdict.toUpperCase()}</span>
        <span className="decision-summary">
          <span className="decision-title">
            {outcome.cart.line_items.map((i) => `${i.name} ×${i.qty}`).join(", ")}
          </span>
          <span className="decision-meta">
            <span>#{index + 1}</span>
            <span>{outcome.cart.id}</span>
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
            <div className="reasons">
              {outcome.reasons.map((reason, i) => (
                <p className={`reason ${outcome.verdict === "block" ? "fail" : "warn"}`} key={i}>
                  <span className="glyph" aria-hidden>
                    {outcome.verdict === "block" ? "×" : "!"}
                  </span>
                  <span>{reason}</span>
                </p>
              ))}
            </div>
          )}

          <ChecksTable checks={outcome.checks} />

          {outcome.receipt && (
            <div className="receipt-strip">
              <span className="ok">receipt</span>
              <span>{outcome.receipt.id}</span>
              <span>rail {outcome.rail?.ref.payment_id ?? outcome.rail?.ref.order_id}</span>
              <Hash value={outcome.cart.digest} />
              {outcome.cart.signature && <span>sig {outcome.cart.signature.key_id}</span>}
            </div>
          )}

          {outcome.rail && !outcome.rail.settled && outcome.rail.ok && (
            <div className="receipt-strip">
              <span>placed on rail, awaiting payment</span>
              <span>{outcome.rail.ref.order_id}</span>
              {typeof outcome.rail.raw.payment_link === "string" && (
                <a href={outcome.rail.raw.payment_link} target="_blank" rel="noreferrer">
                  open payment link
                </a>
              )}
            </div>
          )}

          {outcome.rail && !outcome.rail.ok && (
            <div className="receipt-strip">
              <span style={{ color: "var(--block)" }}>rail failed</span>
              <span>{outcome.rail.error_source}</span>
              <span>{outcome.rail.error_step}</span>
              <span>{outcome.rail.error_reason}</span>
            </div>
          )}

          {outcome.label && <p className="teach">{outcome.label}</p>}
        </div>
      )}
    </article>
  );
}
