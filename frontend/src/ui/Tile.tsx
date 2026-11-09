import type { CSSProperties } from "react";
import {
  IconChecklist,
  IconHome2,
  IconLayoutGrid,
  IconShoppingCart,
  IconSparkles,
  IconWallet,
} from "@tabler/icons-react";

/** Area identifiers retained by the existing page and card components. */
export type Motif =
  | "arcos"
  | "losango"
  | "flor"
  | "catavento"
  | "estrela"
  | "olho";

const icons = {
  arcos: IconLayoutGrid,
  losango: IconWallet,
  flor: IconShoppingCart,
  catavento: IconChecklist,
  estrela: IconHome2,
  olho: IconSparkles,
};

/** A plain section icon used in headings and status controls. */
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
  const Icon = icons[motif];
  return (
    <span
      className={`tile-mark ${className ?? ""}`}
      aria-hidden="true"
      style={{ width: size, height: size, ...style }}
    >
      <Icon size={Math.round(size * 0.6)} stroke={1.8} />
    </span>
  );
}
