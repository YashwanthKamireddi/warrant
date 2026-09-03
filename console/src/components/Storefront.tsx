import { rupees } from "../format";
import type { Product } from "../types";

interface Props {
  catalog: Product[];
  quantities: Record<string, number>;
  merchant: string;
  /** What the signed permission covers. Anything else is marked on the card. */
  permitted?: readonly string[];
  onChange: (sku: string, qty: number) => void;
  disabled: boolean;
}

/** The merchant's shop, as the agent sees it.
 *
 * These are a real storefront's products: their photographs, their titles,
 * their prices. The catalogue deliberately contains things that fall out of
 * scope, and none of them had to be planted -- a coffee merchant sells mugs, and
 * a mandate for food and drink refuses one.
 *
 * Only the two injected product names are ours, and they say so on the card.
 * Claiming a real company had written an instruction into a product title would
 * be a lie about a business that exists.
 */
export function Storefront({
  catalog,
  quantities,
  merchant,
  permitted,
  onChange,
  disabled,
}: Props) {
  const visible = catalog.filter((p) => p.merchant === merchant);
  const covered = permitted ? new Set(permitted) : null;

  return (
    <div className="shop">
      {visible.map((product) => {
        const qty = quantities[product.sku] ?? 0;
        const planted = product.sku.startsWith("warrant-");
        // Out of scope is a property of the product, so the card says it before
        // anybody adds one. Discovering it only after a refusal makes the shop
        // feel like a trick rather than a shop.
        const outOfScope = covered ? !covered.has(product.category) : false;
        return (
          <article
            className={
              `product${qty > 0 ? " picked" : ""}` +
              `${planted ? " planted" : ""}${outOfScope ? " out" : ""}`
            }
            key={product.sku}
          >
            <div className="product-shot" aria-hidden>
              {product.image ? (
                <img
                  src={product.image}
                  alt=""
                  loading="lazy"
                  decoding="async"
                  /* A photograph that fails to load leaves a broken-image icon,
                     which looks worse than the initial it replaces. */
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                  }}
                />
              ) : (
                <span className="product-initial">{product.name.slice(0, 1)}</span>
              )}
            </div>

            <div className="product-body">
              <h4 title={product.name}>{product.name}</h4>
              <p className="product-note">
                <span className={`tag${outOfScope ? " tag-out" : ""}`}>
                  {product.category.replace(/_/g, " ")}
                </span>
                {planted && <span className="tag tag-planted">planted by Warrant</span>}
              </p>
            </div>

            <div className="product-buy">
              <span className="product-price num">
                {rupees(product.unit_paise, { compact: true })}
              </span>
              <span className="stepper">
                <button
                  onClick={() => onChange(product.sku, Math.max(0, qty - 1))}
                  disabled={disabled || qty === 0}
                  aria-label={`Remove one ${product.name}`}
                >
                  −
                </button>
                <span aria-live="polite">{qty}</span>
                <button
                  onClick={() => onChange(product.sku, qty + 1)}
                  disabled={disabled}
                  aria-label={`Add one ${product.name}`}
                >
                  +
                </button>
              </span>
            </div>
          </article>
        );
      })}
    </div>
  );
}
