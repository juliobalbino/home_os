import { motion } from "motion/react";
import type { TargetAndTransition } from "motion/react";
import {
  IconChecklist,
  IconHome2,
  IconLayoutGrid,
  IconShoppingCart,
  IconWallet,
} from "@tabler/icons-react";
import type { Route } from "../lib/route";

/**
 * Icons that move with intent (after itshover's open-source set): each one
 * acts out its area once when hovered or when its area opens.
 */
const icons = {
  painel: IconLayoutGrid,
  financas: IconWallet,
  compras: IconShoppingCart,
  tarefas: IconChecklist,
  casa: IconHome2,
} satisfies Record<Route, unknown>;

const gestures: Record<Route, TargetAndTransition> = {
  painel: {
    rotate: [0, 90],
    transition: { duration: 0.35, ease: [0.2, 0.9, 0.3, 1] },
  },
  financas: {
    y: [0, -3, 0],
    rotate: [0, -8, 0],
    transition: { duration: 0.4 },
  },
  compras: { x: [0, 4, -2, 0], transition: { duration: 0.45 } },
  tarefas: { scale: [1, 1.18, 1], transition: { duration: 0.35 } },
  casa: { y: [0, -4, 0], transition: { duration: 0.4, ease: "easeOut" } },
};

export function NavIcon({ route, active }: { route: Route; active: boolean }) {
  const Icon = icons[route];
  return (
    <motion.span
      className="nav-icon"
      variants={{ hover: gestures[route], active: gestures[route] }}
      animate={active ? "active" : undefined}
      aria-hidden="true"
    >
      <Icon size={22} stroke={active ? 2.2 : 1.7} />
    </motion.span>
  );
}
