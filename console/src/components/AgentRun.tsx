import { rupees } from "../format";
import type { AgentAttempt, Outcome } from "../types";
import { Basket } from "./icons";
import { Empty } from "./primitives";

/** The product as it actually runs.
 *
 * A model reads the instruction and the merchant's catalog, picks a basket and
 * says why. Warrant checks it before any payment exists. If it is refused, the
 * agent is told the reason — not the limits — and tries again.
 *
 * Nobody clicks anything. That is the point: an autonomous system should not be
 * demonstrated by a human pressing plus and minus.
 */
export function AgentRun({
  attempts,
  running,
  cosigned,
  declined,
  busy,
  onApprove,
  onDecline,
  onPlaceOnRazorpay,
  realOrder,
}: {
  attempts: AgentAttempt[];
  running: boolean;
  cosigned: Outcome | null;
  declined: boolean;
  busy: boolean;
  onApprove: (attempt: AgentAttempt) => void;
  onDecline: () => void;
  onPlaceOnRazorpay?: () => void;
  realOrder?: { order_id: string | null; payment_link: string | null };
}) {
  if (attempts.length === 0 && !running) {
    return (
      <Empty icon={<Basket />} title="Let the agent shop">
        A model reads Priya's instruction and the merchant's catalog, picks a basket, and
        says why. Warrant checks it before any payment exists. It is never told her
        spending limits — if it is refused, it only learns the reason.
      </Empty>
    );
  }

  const final = attempts[attempts.length - 1];
  const pendingAsk =
    !running && !cosigned && !declined && final?.outcome.verdict === "escalate"
      ? final
      : null;

  return (
    <div className="run">
      {attempts.map((attempt, i) => {
        const verdict = attempt.outcome.verdict;
        const last = i === attempts.length - 1;
        return (
          <div className="run-step" key={i}>
            <div className="run-spine" aria-hidden>
              <span className={`run-node ${verdict}`} />
              {!last && <span className="run-thread" />}
            </div>

            <div className="run-body">
              <div className="run-turn agent">
                <span className="run-who">
                  <span className="role-glyph agent" aria-hidden>
                    AI
                  </span>
                  The agent
                  {i > 0 && <em>· trying again</em>}
                </span>
                <p className="run-said">{attempt.agent.reasoning}</p>
                <div className="run-picks">
                  {attempt.agent.picks.map((p) => (
                    <span className="run-pick" key={p.sku}>
                      {p.name} <em>×{p.qty}</em>
                    </span>
                  ))}
                  <span className="run-pick total num">
                    {rupees(attempt.agent.total_paise)}
                  </span>
                </div>
              </div>

              <div className={`run-turn gate ${verdict}`}>
                <span className="run-who">
                  <span className={`verdict ${verdict}`}>{verdict.toUpperCase()}</span>
                  Warrant
                  {/* The gate and the model are timed separately, because one
                      number would misrepresent both: the gate runs in
                      microseconds inside the payment path, the advisory judge is
                      a network round trip that only runs on carts which already
                      passed every binding check. */}
                  <em>
                    · {attempt.outcome.checks.length} checks
                    {attempt.outcome.gate_us !== undefined &&
                      ` · gate ${Math.round(attempt.outcome.gate_us)}µs`}
                    {attempt.outcome.model_used &&
                      attempt.outcome.elapsed_us !== undefined &&
                      ` · model ${(attempt.outcome.elapsed_us / 1000).toFixed(1)}ms`}
                  </em>
                </span>
                {attempt.outcome.reasons.length > 0 ? (
                  <ul className="run-reasons">
                    {attempt.outcome.reasons.map((r, j) => (
                      <li key={j}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="run-said">
                    Every bound Priya signed is satisfied. The debit proceeds.
                  </p>
                )}
                {verdict !== "allow" && !last && (
                  <p className="run-handback">
                    The agent is told the reason — never the limits. It has to work it out.
                  </p>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {running && (
        <div className="run-step">
          <div className="run-spine" aria-hidden>
            <span className="run-node pending" />
          </div>
          <div className="run-body">
            <p className="run-thinking">The agent is choosing…</p>
          </div>
        </div>
      )}

      {pendingAsk && (
        <Ask
          attempt={pendingAsk}
          busy={busy}
          onApprove={() => onApprove(pendingAsk)}
          onDecline={onDecline}
        />
      )}

      {declined && !cosigned && (
        <div className="ask settled declined">
          <p className="ask-said">
            You said no, so the basket was never submitted and no money moved.
            Warrant asking is already in the record as a <code>step_up_requested</code>{" "}
            entry — a dispute usually turns on what was stopped, so the stop is
            written down whether or not you go on to approve it.
          </p>
        </div>
      )}

      {cosigned && (
        <Approved
          outcome={cosigned}
          busy={busy}
          onPlaceOnRazorpay={onPlaceOnRazorpay}
          realOrder={realOrder}
        />
      )}
    </div>
  );
}

/** Warrant escalating means one thing: a human has to say yes to this one. The
 *  human is sitting right here, so ask them. */
function Ask({
  attempt,
  busy,
  onApprove,
  onDecline,
}: {
  attempt: AgentAttempt;
  busy: boolean;
  onApprove: () => void;
  onDecline: () => void;
}) {
  return (
    <div className="ask">
      <span className="run-who">
        <span className="role-glyph person" aria-hidden>
          P
        </span>
        Warrant is asking you
      </span>
      <p className="ask-said">
        The agent wants to spend <b className="num">{rupees(attempt.agent.total_paise)}</b>.
        That is over the amount you said needs your say-so, so Warrant stopped and
        came back to you. It cannot approve this by itself, and neither can the
        agent.
      </p>
      <div className="ask-do">
        <button className="btn btn-primary" onClick={onApprove} disabled={busy}>
          {busy ? "Signing…" : "Yes — sign it with my key"}
        </button>
        <button className="btn" onClick={onDecline} disabled={busy}>
          No
        </button>
      </div>
    </div>
  );
}

/** What approving actually did, in the gate's own words.
 *
 *  This must never assume it worked. A co-signature satisfies exactly one
 *  check -- the step-up -- and satisfies nothing else: if the mandate's budget
 *  is already spent, or the basket is out of category, the same signature that
 *  cleared the step-up leaves it blocked. Saying "the money moved" under a
 *  BLOCK is the kind of lie that makes everything else on the page suspect,
 *  and an earlier version of this panel said exactly that. */
function Approved({
  outcome,
  busy,
  onPlaceOnRazorpay,
  realOrder,
}: {
  outcome: Outcome;
  busy: boolean;
  onPlaceOnRazorpay?: () => void;
  realOrder?: { order_id: string | null; payment_link: string | null };
}) {
  const allowed = outcome.verdict === "allow";
  return (
    <div className={`ask settled ${allowed ? "" : "refused"}`}>
      <span className="run-who">
        <span className={`verdict ${outcome.verdict}`}>
          {outcome.verdict.toUpperCase()}
        </span>
        Warrant, again
      </span>
      {allowed ? (
        <p className="ask-said">
          Your key signed the basket, the same gate ran again, and the check that
          failed a moment ago now passes — because a signature exists that did
          not before. The money moved.
        </p>
      ) : (
        <>
          <p className="ask-said">
            Your signature cleared the step-up. It is not an override — it
            satisfies that one check and nothing else, so these still refuse it:
          </p>
          <ul className="run-reasons">
            {outcome.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </>
      )}
      {allowed &&
        (realOrder ? (
          <span className="real-rail placed">
            <b>On Razorpay</b>
            <span className="mono">{realOrder.order_id}</span>
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
          </span>
        ) : (
          onPlaceOnRazorpay && (
            <div className="ask-do">
              <button
                className="btn btn-primary"
                onClick={onPlaceOnRazorpay}
                disabled={busy}
              >
                {busy ? "Placing…" : "Put this on real Razorpay"}
              </button>
            </div>
          )
        ))}
    </div>
  );
}
