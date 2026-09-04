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

/** Category identifiers, said the way the permission was said.
 *
 * `food_beverage` is what the engine calls it and what an acquirer's category
 * code maps to. On screen it read as "food beverage", which is not a phrase.
 */
const CATEGORY_WORDS: Record<string, string> = {
  food_beverage: "food & drink",
  merchandise: "merchandise",
  electronics: "electronics",
  grocery: "groceries",
  pharmacy: "pharmacy",
};

export function categoryWords(categories: readonly string[]): string {
  const said = categories.map((c) => CATEGORY_WORDS[c] ?? c.replace(/_/g, " "));
  if (said.length <= 1) return said[0] ?? "";
  return `${said.slice(0, -1).join(", ")} and ${said[said.length - 1]}`;
}
