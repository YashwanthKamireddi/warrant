import { rupees } from "../format";
import type { AgentAttempt } from "../types";
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
}: {
  attempts: AgentAttempt[];
  running: boolean;
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
    </div>
  );
}
