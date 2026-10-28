import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Anchor, Badge, Button, Text, Title } from "@mantine/core";
import { IconArrowRight } from "@tabler/icons-react";
import { list, reason, request, send } from "../../lib/api";
import type { Balance, Occurrence, Summary } from "../../lib/api";
import {
  DEFAULT_TIME_ZONE,
  dateTime,
  localPeriod,
  money,
  quantity,
  today,
} from "../../lib/format";
import { href } from "../../lib/route";
import type { Route } from "../../lib/route";
import { useToast } from "../../ui/Toaster";
import { TileMark } from "../../ui/Tile";
import type { Motif } from "../../ui/Tile";
import {
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  TileMeter,
} from "../../ui/parts";

type Section<T> = { data: T | null; error: string; loading: boolean };
type ShoppingList = {
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

function useSection<T>(loader: () => Promise<T>, key: string): Section<T> {
  const [state, setState] = useState<Section<T>>({
    data: null,
    error: "",
    loading: true,
  });
  useEffect(() => {
    let active = true;
    setState({ data: null, error: "", loading: true });
    loader()
      .then((data) => active && setState({ data, error: "", loading: false }))
      .catch((cause: unknown) => {
        if (active)
          setState({
            data: null,
            error:
              cause instanceof Error ? cause.message : "Falha ao carregar.",
            loading: false,
          });
      });
    return () => {
      active = false;
    };
    // The key holds every changing input of the loader.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return state;
}

function Panel({
  motif,
  title,
  id,
  route,
  linkLabel,
  className,
  children,
}: {
  motif: Motif;
  title: string;
  id: string;
  route: Route;
  linkLabel: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section
      className={`tile dash-tile ${className ?? ""}`}
      aria-labelledby={id}
    >
      <div className="tile-head">
        <TileMark motif={motif} size={28} />
        <Title order={2} id={id}>
          {title}
        </Title>
      </div>
      <div className="dash-body">{children}</div>
      <Anchor href={href(route)} className="dash-link" fw={600}>
        {linkLabel}
        <IconArrowRight size={16} aria-hidden="true" />
      </Anchor>
    </section>
  );
}

export default function Dashboard({
  householdId,
  householdName,
  role,
  timezone = DEFAULT_TIME_ZONE,
  children,
}: {
  householdId: string;
  householdName: string;
  role?: string;
  timezone?: string;
  children?: ReactNode;
}) {
  const now = new Date();
  const writable = Boolean(role) && role !== "viewer";
  const toast = useToast();
  const [handled, setHandled] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState("");
  async function act(key: string, call: () => Promise<unknown>, done: string) {
    setActionError("");
    try {
      await call();
      setHandled((current) => new Set(current).add(key));
      toast.success(done);
    } catch (cause) {
      setActionError(reason(cause, "Não foi possível concluir a ação."));
    }
  }
  const period = localPeriod(now, timezone);
  const finance = useSection(async () => {
    const [summary, balances] = await Promise.all([
      request<Summary>(
        `/households/${householdId}/financial-summary?period=${period}`,
      ),
      request<Balance[]>(`/households/${householdId}/settlements`),
    ]);
    return {
      spent: summary?.spent_total ?? 0,
      budget: summary?.budget_total ?? 0,
      balances: list<Balance>(balances),
    };
  }, `${householdId}|${period}`);
  const shopping = useSection(async () => {
    const lists = list<ShoppingList>(
      await request<ShoppingList[]>(
        `/households/${householdId}/shopping-lists`,
      ),
    );
    return lists
      .filter((entry) => entry.status === "active")
      .flatMap((entry) =>
        list<ShoppingList["items"][number]>(entry.items)
          .filter((item) => item.status === "needed")
          .map((item) => ({ ...item, listName: entry.name })),
      );
  }, householdId);
  const chores = useSection(
    async () =>
      list<Occurrence>(
        await request(`/households/${householdId}/chore-occurrences`),
      ),
    householdId,
  );
  const toBuy = (shopping.data ?? []).filter(
    (item) => !handled.has(`s${item.id}`),
  );
  const due = (chores.data ?? [])
    .filter((item) => item.status === "pending" && !handled.has(`c${item.id}`))
    .sort((a, b) => a.due_at.localeCompare(b.due_at));

  return (
    <div className="page dashboard">
      <PageHeader motif="arcos" title={householdName} id="dashboard-title">
        <span className="capitalize">{today(timezone)}</span>
      </PageHeader>

      {actionError && <ErrorNote>{actionError}</ErrorNote>}
      <div className="tile-wall dashboard-grid">
        <Panel
          motif="losango"
          title="Finanças deste mês"
          id="dashboard-finance-title"
          route="financas"
          linkLabel="Abrir finanças"
          className="dash-finance"
        >
          {finance.loading ? (
            <Loading label="Carregando finanças…" />
          ) : finance.error ? (
            <ErrorNote label="Erro em finanças">{finance.error}</ErrorNote>
          ) : (
            <>
              <p className="statement">
                <strong>{money(finance.data!.spent)}</strong> em gastos do mês
                {finance.data!.budget > 0 ? (
                  <>
                    ; orçamento restante de{" "}
                    <strong>
                      {money(
                        Math.max(0, finance.data!.budget - finance.data!.spent),
                      )}
                    </strong>
                    .
                  </>
                ) : (
                  ", sem orçamento definido."
                )}
              </p>
              {finance.data!.budget > 0 && (
                <TileMeter
                  value={finance.data!.spent}
                  total={finance.data!.budget}
                />
              )}
              {finance.data!.spent === 0 && (
                <Text size="sm" c="dimmed">
                  Sem gastos registrados neste mês.
                </Text>
              )}
              {finance.data!.balances.length ? (
                <ul className="rows rows-compact">
                  {finance.data!.balances.map((balance) => (
                    <li key={balance.membership_id} className="row">
                      <span className="row-main">{balance.name}</span>
                      <span
                        className="amount"
                        data-negative={balance.balance_minor < 0 || undefined}
                      >
                        {money(balance.balance_minor)}{" "}
                        <small>
                          {balance.balance_minor < 0
                            ? "a acertar"
                            : "de crédito"}
                        </small>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <Text size="sm" c="dimmed">
                  Sem saldos para acertar.
                </Text>
              )}
            </>
          )}
        </Panel>

        <Panel
          motif="flor"
          title="Lista de compras"
          id="dashboard-shopping-title"
          route="compras"
          linkLabel="Abrir compras e estoque"
        >
          {shopping.loading ? (
            <Loading label="Carregando lista…" />
          ) : shopping.error ? (
            <ErrorNote label="Erro em compras">{shopping.error}</ErrorNote>
          ) : toBuy.length ? (
            <ul className="rows rows-compact">
              {toBuy.slice(0, 7).map((item) => (
                <li key={item.id} className="row">
                  <span className="row-main">{item.name}</span>
                  <span className="row-meta">
                    {quantity(item.quantity)} {item.unit}
                  </span>
                  {writable && (
                    <Button
                      size="compact-sm"
                      variant="light"
                      aria-label={`Marcar ${item.name} como comprado`}
                      onClick={() =>
                        void act(
                          `s${item.id}`,
                          () =>
                            send(
                              `/shopping-items/${item.id}`,
                              { status: "purchased" },
                              "PATCH",
                            ),
                          "Item marcado como comprado.",
                        )
                      }
                    >
                      Comprei
                    </Button>
                  )}
                </li>
              ))}
              {toBuy.length > 7 && (
                <li className="row row-more">
                  e mais {toBuy.length - 7} itens
                </li>
              )}
            </ul>
          ) : (
            <EmptyState>Nenhum item pendente nas listas ativas.</EmptyState>
          )}
        </Panel>

        <Panel
          motif="catavento"
          title="Tarefas vencidas e próximas"
          id="dashboard-chores-title"
          route="tarefas"
          linkLabel="Abrir tarefas e rotinas"
        >
          {chores.loading ? (
            <Loading label="Carregando tarefas…" />
          ) : chores.error ? (
            <ErrorNote label="Erro em tarefas">{chores.error}</ErrorNote>
          ) : due.length ? (
            <ul className="rows rows-compact">
              {due.slice(0, 6).map((item) => {
                const late = new Date(item.due_at) < now;
                return (
                  <li key={item.id} className="row">
                    <span className="row-main">
                      <span className="row-title">{item.title}</span>
                      <span className="row-meta">
                        {dateTime(item.due_at, timezone)}
                      </span>
                    </span>
                    {writable ? (
                      <Button
                        size="compact-sm"
                        variant="light"
                        color={late ? "ocre.5" : "azulejo"}
                        aria-label={`Concluir ${item.title}`}
                        onClick={() =>
                          void act(
                            `c${item.id}`,
                            () =>
                              send(`/chore-occurrences/${item.id}/complete`, {
                                status: "completed",
                              }),
                            "Ocorrência concluída.",
                          )
                        }
                      >
                        {late ? "Atrasada · Concluir" : "Concluir"}
                      </Button>
                    ) : (
                      <Badge variant="light" color={late ? "ocre" : "azulejo"}>
                        {late ? "Atrasada" : "Pendente"}
                      </Badge>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState>Nenhuma tarefa pendente.</EmptyState>
          )}
        </Panel>
      </div>
      {children}
    </div>
  );
}
