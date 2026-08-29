/** A tiny hand-drawn icon set.
 *
 * No icon library: every glyph here is 16px on a 16px grid at a single stroke
 * weight, which keeps them optically consistent with 13.5px text in a way a
 * mixed-provenance icon set never is. It also keeps the bundle self-contained.
 */

const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const ShieldMark = ({ size = 18 }: { size?: number }) => (
  <svg {...base} width={size} height={size} strokeWidth={1.6}>
    <path d="M8 1.75 13 3.5v4.1c0 3-2.1 5.4-5 6.65-2.9-1.25-5-3.65-5-6.65V3.5L8 1.75Z" />
    <path d="M5.9 7.9 7.4 9.4l2.9-3" />
  </svg>
);

export const Chevron = () => (
  <svg {...base} width={10} height={10} viewBox="0 0 10 10">
    <path d="M3.5 1.5 7 5 3.5 8.5" />
  </svg>
);

export const Doc = ({ size = 16 }: { size?: number }) => (
  <svg {...base} width={size} height={size}>
    <path d="M9 1.5H4.5A1.5 1.5 0 0 0 3 3v10a1.5 1.5 0 0 0 1.5 1.5h7A1.5 1.5 0 0 0 13 13V5.5L9 1.5Z" />
    <path d="M9 1.5V5.5H13M5.5 8.5h5M5.5 11h3" />
  </svg>
);

export const Rows = ({ size = 16 }: { size?: number }) => (
  <svg {...base} width={size} height={size}>
    <path d="M2 4h12M2 8h12M2 12h12" />
  </svg>
);

export const Basket = ({ size = 16 }: { size?: number }) => (
  <svg {...base} width={size} height={size}>
    <path d="M2.5 5.5h11l-1 8h-9l-1-8Z" />
    <path d="M5.5 5.5 8 2l2.5 3.5" />
  </svg>
);
