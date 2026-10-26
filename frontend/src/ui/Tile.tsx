import { useId } from "react";
import type { CSSProperties, ReactNode } from "react";

/**
 * Hydraulic tile motifs, one per area of the house. Each is drawn on a
 * 40×40 unit so four tiles meet into a larger figure, as on a kitchen wall.
 * Colors come from --m-base (cement), --m-a (glaze) and --m-b (ochre).
 */
export type Motif =
  | "arcos"
  | "losango"
  | "flor"
  | "catavento"
  | "estrela"
  | "olho";

const A = "var(--m-a)";
const B = "var(--m-b)";
const BASE = "var(--m-base)";

function Figure({ motif }: { motif: Motif }): ReactNode {
  switch (motif) {
    case "arcos":
      return (
        <>
          <path d="M0 0H20A20 20 0 0 1 0 20Z" fill={A} />
          <path d="M40 0V20A20 20 0 0 1 20 0Z" fill={A} />
          <path d="M40 40H20A20 20 0 0 1 40 20Z" fill={A} />
          <path d="M0 40V20A20 20 0 0 1 20 40Z" fill={A} />
          <path d="M0 0H10A10 10 0 0 1 0 10Z" fill={BASE} />
          <path d="M40 0V10A10 10 0 0 1 30 0Z" fill={BASE} />
          <path d="M40 40H30A10 10 0 0 1 40 30Z" fill={BASE} />
          <path d="M0 40V30A10 10 0 0 1 10 40Z" fill={BASE} />
          <circle cx="20" cy="20" r="3.5" fill={B} />
        </>
      );
    case "losango":
      return (
        <>
          <path d="M20 5L35 20L20 35L5 20Z" fill={A} />
          <path d="M20 12L28 20L20 28L12 20Z" fill={BASE} />
          <circle cx="20" cy="20" r="3" fill={B} />
          <path d="M0 0H7A7 7 0 0 1 0 7Z" fill={B} />
          <path d="M40 0V7A7 7 0 0 1 33 0Z" fill={B} />
          <path d="M40 40H33A7 7 0 0 1 40 33Z" fill={B} />
          <path d="M0 40V33A7 7 0 0 1 7 40Z" fill={B} />
        </>
      );
    case "flor":
      return (
        <>
          {[0, 90, 180, 270].map((angle) => (
            <ellipse
              key={angle}
              cx="20"
              cy="10.5"
              rx="5"
              ry="8.5"
              fill={A}
              transform={`rotate(${angle} 20 20)`}
            />
          ))}
          {[45, 135, 225, 315].map((angle) => (
            <ellipse
              key={angle}
              cx="20"
              cy="12"
              rx="2.2"
              ry="5"
              fill={B}
              transform={`rotate(${angle} 20 20)`}
            />
          ))}
          <circle cx="20" cy="20" r="4" fill={BASE} />
          <circle cx="20" cy="20" r="2" fill={B} />
          <path
            d="M0 9A9 9 0 0 0 9 0M31 0A9 9 0 0 0 40 9M40 31A9 9 0 0 0 31 40M9 40A9 9 0 0 0 0 31"
            fill="none"
            stroke={A}
            strokeWidth="2.5"
          />
        </>
      );
    case "catavento":
      return (
        <>
          {[0, 90, 180, 270].map((angle) => (
            <path
              key={angle}
              d="M20 20L20 1L39 1Z"
              fill={A}
              transform={`rotate(${angle} 20 20)`}
            />
          ))}
          {[0, 90, 180, 270].map((angle) => (
            <path
              key={`b${angle}`}
              d="M20 20L1 1L20 1Z"
              fill={B}
              opacity="0.9"
              transform={`rotate(${angle} 20 20)`}
            />
          ))}
          <circle cx="20" cy="20" r="4.5" fill={BASE} />
          <circle cx="20" cy="20" r="2" fill={A} />
        </>
      );
    case "estrela":
      return (
        <>
          <path d="M11 11H29V29H11Z" fill={A} />
          <path d="M11 11H29V29H11Z" fill={A} transform="rotate(45 20 20)" />
          <circle cx="20" cy="20" r="5.5" fill={BASE} />
          <circle cx="20" cy="20" r="2.5" fill={B} />
          <path
            d="M0 0H5V5H0ZM35 0H40V5H35ZM35 35H40V40H35ZM0 35H5V40H0Z"
            fill={B}
          />
        </>
      );
    case "olho":
      return (
        <>
          <circle cx="20" cy="20" r="16" fill={A} />
          <circle cx="20" cy="20" r="11" fill={BASE} />
          <circle cx="20" cy="20" r="6.5" fill={B} />
          <circle cx="20" cy="20" r="2.5" fill={BASE} />
          <path
            d="M0 0H6A6 6 0 0 1 0 6ZM40 0V6A6 6 0 0 1 34 0ZM40 40H34A6 6 0 0 1 40 34ZM0 40V34A6 6 0 0 1 6 40Z"
            fill={A}
          />
        </>
      );
  }
}

/** One glazed tile, used as the identity mark of an area. */
export function TileMark({
  motif,
  size = 40,
  className,
  style,
}: {
  motif: Motif;
  size?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const id = useId();
  return (
    <svg
      className={`tile-mark ${className ?? ""}`}
      width={size}
      height={size}
      viewBox="0 0 40 40"
      aria-hidden="true"
      focusable="false"
      style={style}
    >
      <defs>
        <linearGradient id={`${id}-sheen`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.28" />
          <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <clipPath id={`${id}-clip`}>
          <rect width="40" height="40" rx="3" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        <rect width="40" height="40" fill={BASE} />
        <Figure motif={motif} />
        <rect width="40" height="40" fill={`url(#${id}-sheen)`} />
      </g>
    </svg>
  );
}

/**
 * A run of tiles filling its box: the "barrado" band under page titles and the
 * wall behind the sign-in form. Alternate motifs checker across the run.
 */
export function TileRun({
  motifs,
  size = 40,
  className,
}: {
  motifs: [Motif] | [Motif, Motif];
  size?: number;
  className?: string;
}) {
  const id = useId();
  const [first, second = first] = motifs;
  const unit = size * 2;
  const scale = size / 40;
  return (
    <svg
      className={`tile-run ${className ?? ""}`}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <pattern
          id={id}
          width={unit}
          height={unit}
          patternUnits="userSpaceOnUse"
        >
          <g transform={`scale(${scale})`}>
            <rect width="80" height="80" fill={BASE} />
            <Figure motif={first} />
            <g transform="translate(40 0)">
              <Figure motif={second} />
            </g>
            <g transform="translate(0 40)">
              <Figure motif={second} />
            </g>
            <g transform="translate(40 40)">
              <Figure motif={first} />
            </g>
            <path
              d="M0 0V80M40 0V80M0 0H80M0 40H80"
              stroke="var(--m-grout)"
              strokeWidth="1.5"
            />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}
