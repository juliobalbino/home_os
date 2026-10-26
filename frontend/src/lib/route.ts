import { useEffect, useState } from "react";

export const ROUTES = [
  "painel",
  "financas",
  "compras",
  "tarefas",
  "casa",
] as const;
export type Route = (typeof ROUTES)[number];

function parse(hash: string): Route {
  const name = hash.replace(/^#\/?/, "").split(/[/?]/)[0];
  return (ROUTES as readonly string[]).includes(name)
    ? (name as Route)
    : "painel";
}

export const href = (route: Route) => `#/${route}`;

/** Minimal hash router: deep links and the back button work without a server. */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parse(window.location.hash));
  useEffect(() => {
    const sync = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo?.({ top: 0 });
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);
  return route;
}
