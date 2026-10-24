import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
type Section<T> = { data: T | null; error: string; loading: boolean };
type Summary = { spent_total: number; budget_total: number };
type Balance = { membership_id: number; name: string; balance_minor: number };
type List = {
  id: number;
  name: string;
  status: string;
  items: {
    id: number;
    name: string;
    quantity: string;
    unit: string;
    status: string;
  }[];
};
type Occurrence = {
  id: number;
  title: string;
  due_at: string;
  status: string;
  assigned_name?: string | null;
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: "include" });
  const data = await response.json();
  if (!response.ok)
    throw new Error(data.detail ?? "Não foi possível carregar esta seção.");
  return data as T;
}

function money(cents: number) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL",
  }).format(cents / 100);
}

function useSection<T>(loader: () => Promise<T>, deps: string[]): Section<T> {
  const [state, setState] = useState<Section<T>>({
    data: null,
    error: "",
    loading: true,
  });
  useEffect(() => {
    let active = true;
    setState({ data: null, error: "", loading: true });
    void loader()
      .then((data) => {
        if (active) setState({ data, error: "", loading: false });
      })
      .catch((reason: unknown) => {
        if (active)
          setState({
            data: null,
            error:
              reason instanceof Error ? reason.message : "Falha ao carregar.",
            loading: false,
          });
      });
    return () => {
      active = false;
    };
    // The household ID is the loader's only changing input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export default function Dashboard({
  householdId,
  householdName,
}: {
  householdId: string;
  householdName: string;
}) {
  const now = new Date();
  const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const finance = useSection(async () => {
    const [summary, balances] = await Promise.all([
      get<Summary>(
        `/households/${householdId}/financial-summary?period=${period}`,
      ),
      get<Balance[]>(`/households/${householdId}/settlements`),
    ]);
    return { summary, balances };
  }, [householdId, period]);
  const shopping = useSection(async () => {
    const lists = await get<List[]>(
      `/households/${householdId}/shopping-lists`,
    );
    return lists
      .filter((list) => list.status === "active")
      .flatMap((list) =>
        list.items
          .filter((item) => item.status === "needed")
          .map((item) => ({ ...item, listName: list.name })),
      );
  }, [householdId]);
  const chores = useSection(
    () => get<Occurrence[]>(`/households/${householdId}/chore-occurrences`),
    [householdId],
  );
  const due = (chores.data ?? [])
    .filter((item) => item.status === "pending")
    .sort((a, b) => a.due_at.localeCompare(b.due_at));
  return (
    <section className="dashboard" aria-labelledby="dashboard-title">
      <p className="eyebrow">VISÃO GERAL DA RESIDÊNCIA</p>
      <h1 id="dashboard-title">{householdName}</h1>
      <div className="dashboard-grid">
        <section
          className="dashboard-card"
          aria-labelledby="dashboard-finance-title"
        >
          <h2 id="dashboard-finance-title">Finanças deste mês</h2>
          {finance.loading ? (
            <p role="status">Carregando finanças…</p>
          ) : finance.error ? (
            <p role="alert" aria-label="Erro em finanças">
              {finance.error}
            </p>
          ) : (
            <>
              <p>
                Gastos do mês{" "}
                <strong>{money(finance.data!.summary.spent_total)}</strong>
              </p>
              <p>
                Orçamento restante{" "}
                <strong>
                  {money(
                    Math.max(
                      0,
                      finance.data!.summary.budget_total -
                        finance.data!.summary.spent_total,
                    ),
                  )}
                </strong>
              </p>
              {finance.data!.balances.length ? (
                <ul>
                  {finance.data!.balances.map((balance) => (
                    <li key={balance.membership_id}>
                      {balance.name}: {money(balance.balance_minor)}{" "}
                      {balance.balance_minor < 0 ? "a acertar" : "de crédito"}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">Sem saldos para acertar.</p>
              )}
              {finance.data!.summary.spent_total === 0 && (
                <p className="empty">Sem gastos registrados neste mês.</p>
              )}
            </>
          )}
          <a
            href="#financas"
            onClick={(event) => {
              event.preventDefault();
              window.dispatchEvent(
                new CustomEvent("home-os:open", { detail: "finance" }),
              );
            }}
          >
            Abrir finanças
          </a>
        </section>
        <section
          className="dashboard-card"
          aria-labelledby="dashboard-shopping-title"
        >
          <h2 id="dashboard-shopping-title">Lista de compras</h2>
          {shopping.loading ? (
            <p role="status">Carregando lista…</p>
          ) : shopping.error ? (
            <p role="alert" aria-label="Erro em compras">
              {shopping.error}
            </p>
          ) : shopping.data!.length ? (
            <ul>
              {shopping.data!.map((item) => (
                <li key={item.id}>
                  {item.name} · {item.quantity} {item.unit}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">Nenhum item pendente nas listas ativas.</p>
          )}
          <a
            href="#compras"
            onClick={(event) => {
              event.preventDefault();
              window.dispatchEvent(
                new CustomEvent("home-os:open", { detail: "shopping" }),
              );
            }}
          >
            Abrir compras e estoque
          </a>
        </section>
        <section
          className="dashboard-card"
          aria-labelledby="dashboard-chores-title"
        >
          <h2 id="dashboard-chores-title">Tarefas vencidas e próximas</h2>
          {chores.loading ? (
            <p role="status">Carregando tarefas…</p>
          ) : chores.error ? (
            <p role="alert" aria-label="Erro em tarefas">
              {chores.error}
            </p>
          ) : due.length ? (
            <ul>
              {due.map((item) => (
                <li key={item.id}>
                  {item.title} ·{" "}
                  {new Intl.DateTimeFormat("pt-BR", {
                    dateStyle: "short",
                    timeStyle: "short",
                  }).format(new Date(item.due_at))}
                  {new Date(item.due_at) < now ? " · Atrasada" : " · Pendente"}
                </li>
              ))}
            </ul>
          ) : (
            <p className="empty">Nenhuma tarefa pendente.</p>
          )}
          <a
            href="#tarefas"
            onClick={(event) => {
              event.preventDefault();
              window.dispatchEvent(
                new CustomEvent("home-os:open", { detail: "chores" }),
              );
            }}
          >
            Abrir tarefas e rotinas
          </a>
        </section>
      </div>
    </section>
  );
}
