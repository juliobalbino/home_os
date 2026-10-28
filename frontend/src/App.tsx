import { useCallback, useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AuthScreen } from "./auth/AuthScreen";
import { HouseholdPage } from "./household/HouseholdPage";
import { Onboarding } from "./household/Onboarding";
import { list, request, send } from "./lib/api";
import type { Household, User } from "./lib/api";
import { DEFAULT_TIME_ZONE } from "./lib/format";
import { useRoute } from "./lib/route";
import Assistant from "./modules/assistant/Assistant";
import Chores from "./modules/chores/Chores";
import Dashboard from "./modules/dashboard/Dashboard";
import Finance from "./modules/finance/Finance";
import Shopping from "./modules/shopping/Shopping";
import { AppFrame } from "./shell/AppFrame";
import { TileMark } from "./ui/Tile";

type Session =
  | { state: "loading" }
  | { state: "anonymous" }
  | { state: "ready"; user: User; houses: Household[] };

export default function App() {
  const [session, setSession] = useState<Session>({ state: "loading" });
  const route = useRoute();

  const refresh = useCallback(async () => {
    try {
      const user = await request<User>("/me");
      const houses = list<Household>(await request<Household[]>("/households"));
      setSession({ state: "ready", user, houses });
    } catch {
      setSession({ state: "anonymous" });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function signOut() {
    try {
      await send("/auth/logout", {});
    } finally {
      setSession({ state: "anonymous" });
      window.location.hash = "";
    }
  }

  if (session.state === "loading")
    return (
      <div className="splash" role="status">
        <TileMark motif="estrela" size={56} className="splash-mark" />
        <span className="sr-only">Carregando o Home OS…</span>
      </div>
    );
  if (session.state === "anonymous") return <AuthScreen onSignedIn={refresh} />;

  const { user, houses } = session;
  // The backend allows one active membership per person.
  const house = houses[0];
  if (!house)
    return (
      <Onboarding
        user={user}
        onJoined={refresh}
        onSignOut={() => void signOut()}
      />
    );
  const timezone = house.timezone || DEFAULT_TIME_ZONE;

  return (
    <AppFrame route={route} household={house} user={user}>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={route}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, transition: { duration: 0.08 } }}
          transition={{ duration: 0.2, ease: [0.2, 0.9, 0.3, 1] }}
        >
          {route === "painel" && (
            <Dashboard
              householdId={house.id}
              householdName={house.name}
              role={house.role}
              timezone={timezone}
            >
              <Assistant householdId={house.id} role={house.role} compact />
            </Dashboard>
          )}
          {route === "financas" && (
            <Finance
              householdId={house.id}
              role={house.role}
              timezone={timezone}
            />
          )}
          {route === "compras" && (
            <Shopping
              householdId={house.id}
              role={house.role}
              timezone={timezone}
            />
          )}
          {route === "tarefas" && (
            <Chores
              householdId={house.id}
              role={house.role}
              timezone={timezone}
            />
          )}
          {route === "casa" && (
            <HouseholdPage
              household={house}
              user={user}
              onSignOut={() => void signOut()}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </AppFrame>
  );
}
