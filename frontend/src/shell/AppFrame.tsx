import type { ReactNode } from "react";
import { motion } from "motion/react";
import { NativeSelect, Text } from "@mantine/core";
import { href } from "../lib/route";
import type { Route } from "../lib/route";
import type { Household, User } from "../lib/api";
import { NavIcon } from "../ui/NavIcon";
import { TileMark, TileRun } from "../ui/Tile";

const items: { route: Route; label: string }[] = [
  { route: "painel", label: "Painel" },
  { route: "financas", label: "Finanças" },
  { route: "compras", label: "Compras" },
  { route: "tarefas", label: "Tarefas" },
  { route: "casa", label: "Casa" },
];

/**
 * One navigation list that sits as a sidebar on wide screens and as a bottom
 * bar on phones, so the active tile can slide between areas in either form.
 */
export function AppFrame({
  route,
  household,
  user,
  children,
  onHouseholdChange,
  households = [household],
  allowOnboarding = false,
}: {
  route: Route;
  household: Household;
  user: User;
  children: ReactNode;
  onHouseholdChange?: (id: string) => void;
  households?: Household[];
  allowOnboarding?: boolean;
}) {
  return (
    <div className="frame">
      <a className="skip" href="#conteudo">
        Pular para o conteúdo
      </a>
      <header className="frame-top">
        <a className="brand" href={href("painel")}>
          <TileMark motif="estrela" size={30} />
          <span>Home OS</span>
        </a>
        <div className="frame-household-control">
          <NativeSelect
            aria-label="Residência"
            className="frame-house"
            value={household.id}
            onChange={(event) => onHouseholdChange?.(event.currentTarget.value)}
            data={[
              ...households.map((item) => ({
                value: item.id,
                label: item.isArchived
                  ? `${item.name} — arquivada (somente leitura)`
                  : item.name,
              })),
              ...(allowOnboarding
                ? [
                    {
                      value: "__onboarding__",
                      label: "Criar/entrar em outra residência",
                    },
                  ]
                : []),
            ]}
          />
        </div>
      </header>
      <nav className="frame-nav" aria-label="Principal">
        <ul>
          {items.map((item) => {
            const active = item.route === route;
            return (
              <li key={item.route}>
                <motion.a
                  href={href(item.route)}
                  className="nav-link"
                  aria-current={active ? "page" : undefined}
                  whileHover="hover"
                >
                  {active && (
                    <motion.span
                      layoutId="nav-active"
                      className="nav-active"
                      transition={{
                        type: "spring",
                        stiffness: 480,
                        damping: 36,
                      }}
                    />
                  )}
                  <NavIcon route={item.route} active={active} />
                  <span className="nav-label">{item.label}</span>
                </motion.a>
              </li>
            );
          })}
        </ul>
        <TileRun
          motifs={["arcos", "estrela"]}
          size={28}
          className="nav-tiles"
        />
        <div className="frame-user">
          <Text size="sm" fw={600} truncate>
            {user.name}
          </Text>
        </div>
      </nav>
      <main className="frame-main" id="conteudo" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
