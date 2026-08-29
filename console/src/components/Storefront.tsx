import { rupees } from "../format";
import type { Product } from "../types";

interface Props {
  catalog: Product[];
  quantities: Record<string, number>;
  merchant: string;
  onChange: (sku: string, qty: number) => void;
  disabled: boolean;
}

/** The agent's basket. The catalog deliberately contains items that drift out of
 *  scope -- wrong category, wrong merchant, an injected instruction sitting in a
 *  product name -- because a control plane you can only demonstrate on the happy
 *  path demonstrates nothing. */
export function Storefront({ catalog, quantities, merchant, onChange, disabled }: Props) {
  const visible = catalog.filter((p) => p.merchant === merchant);

  return (
    <div className="catalog">
      {visible.map((product) => {
        const qty = quantities[product.sku] ?? 0;
        return (
          <div className="product" key={product.sku}>
            <span className="product-name">
              <span title={product.name}>{product.name}</span>
              <em>{product.note}</em>
            </span>
            <span className="product-price">{rupees(product.unit_paise, { compact: true })}</span>
            <span className="qty">
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
        );
      })}
    </div>
  );
}
