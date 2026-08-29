/** Money is integer paise everywhere, including here. It is never a float in
 *  transit and never a float on screen -- the divide happens at the last moment,
 *  for display only. */

export function rupees(paise: number, opts: { compact?: boolean } = {}): string {
  const value = paise / 100;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: opts.compact && Number.isInteger(value) ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function shortHash(hash: string, chars = 10): string {
  return hash.replace(/^sha256:/, "").slice(0, chars);
}

export function clockTime(unix: number): string {
  return new Date(unix * 1000).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function relativeWindow(from: number, to: number): string {
  const minutes = Math.round((to - from) / 60);
  if (minutes < 60) return `${minutes} min`;
  const hours = minutes / 60;
  return Number.isInteger(hours) ? `${hours} hr` : `${hours.toFixed(1)} hr`;
}

/** Rule names read as `scope.per_txn_ceiling`. Keep them verbatim -- an operator
 *  should be able to grep the codebase for exactly what they see on screen. */
export function ruleLabel(rule: string): string {
  return rule;
}
