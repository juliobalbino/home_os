import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Badge,
  Button,
  Checkbox,
  Collapse,
  Group,
  NativeSelect,
  Text,
  TextInput,
} from "@mantine/core";
import { IconCash, IconPlus } from "@tabler/icons-react";
import { list, reason, request, send } from "../../lib/api";
import type { Balance, Member, Summary } from "../../lib/api";
import {
  DEFAULT_TIME_ZONE,
  isoDay,
  localDay,
  localPeriod,
  money,
  monthName,
  parseMoney,
} from "../../lib/format";
import { useToast } from "../../ui/Toaster";
import { SectionNav } from "../../ui/SectionNav";
import {
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  TileMeter,
  TileSection,
} from "../../ui/parts";

type Category = { id: number; name: string; kind: string };
type Expense = {
  id: number;
  description: string;
  category: string;
  amount_minor: number;
  paid_total: number;
  status: string;
  incurred_on: string;
  splits: {
    membership_id: number;
    member_name: string;
    amount_minor: number;
  }[];
};

const STATUS: Record<string, { label: string; color: string }> = {
  paid: { label: "Paga", color: "azulejo" },
  partial: { label: "Parcialmente paga", color: "ocre" },
};

function dayParts(day: string) {
  const [year, month, date] = day.split("-").map(Number);
  if (!year || !month || !date) return { day: "", month: day };
  return {
    day: String(date),
    month: new Intl.DateTimeFormat("pt-BR", { month: "short" })
      .format(new Date(year, month - 1, date))
      .replace(".", ""),
  };
}

function PaymentForm({
  expense,
  members,
  busy,
  onPay,
}: {
  expense: Expense;
  members: Member[];
  busy: boolean;
  onPay: (
    event: FormEvent<HTMLFormElement>,
    expenseId: number,
  ) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="payment">
      <Button
        size="xs"
        variant="subtle"
        leftSection={<IconCash size={14} aria-hidden="true" />}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? "Fechar pagamento" : "Registrar pagamento"}
      </Button>
      <Collapse expanded={open}>
        <form
          className="payment-form"
          onSubmit={(event) => void onPay(event, expense.id)}
        >
          <TextInput
            label="Registrar pagamento (R$)"
            name="amount"
            inputMode="decimal"
            required
            placeholder="0,00"
            size="sm"
            defaultValue={money(
              expense.amount_minor - expense.paid_total,
            ).replace("R$ ", "")}
          />
          <NativeSelect
            label="Pago por"
            name="payer_id"
            size="sm"
            data={members.map((member) => ({
              value: String(member.id),
              label: member.name,
            }))}
          />
          <Button type="submit" size="sm" loading={busy}>
            Salvar pagamento
          </Button>
        </form>
      </Collapse>
    </div>
  );
}

export default function Finance({
  householdId,
  role,
  timezone = DEFAULT_TIME_ZONE,
}: {
  householdId: string;
  role: string;
  timezone?: string;
}) {
  const canWrite = role === "owner" || role === "member";
  const [categories, setCategories] = useState<Category[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [summary, setSummary] = useState<Summary>({
    spent_total: 0,
    budget_total: 0,
  });
  const [balances, setBalances] = useState<Balance[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [splitMethod, setSplitMethod] = useState("equal");
  const [period] = useState(() => localPeriod(new Date(), timezone));
  const toast = useToast();

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [categoryRows, memberRows, expenseRows, summaryRow, balanceRows] =
        await Promise.all([
          request<Category[]>(
            `/finance/categories?household_id=${householdId}`,
          ),
          request<Member[]>(`/households/${householdId}/members`),
          request<Expense[]>(`/households/${householdId}/expenses`),
          request<Summary>(
            `/households/${householdId}/financial-summary?period=${period}`,
          ),
          request<Balance[]>(`/households/${householdId}/settlements`),
        ]);
      setCategories(list<Category>(categoryRows));
      setMembers(list<Member>(memberRows));
      setExpenses(list<Expense>(expenseRows));
      setSummary({
        spent_total: summaryRow?.spent_total ?? 0,
        budget_total: summaryRow?.budget_total ?? 0,
      });
      setBalances(list<Balance>(balanceRows));
    } catch (cause) {
      setError(reason(cause, "Não foi possível carregar as finanças."));
    } finally {
      setLoading(false);
    }
  }, [householdId, period]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function mutate(
    path: string,
    payload: unknown,
    method = "POST",
  ): Promise<boolean> {
    setBusy(true);
    setError("");
    try {
      await send(path, payload, method);
      toast.success("Alterações salvas com sucesso.");
      await refresh();
      return true;
    } catch (cause) {
      setError(reason(cause, "Não foi possível salvar."));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submitCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const name = new FormData(form).get("name");
    if (
      await mutate(`/finance/categories`, { household_id: householdId, name })
    )
      form.reset();
  }

  async function submitExpense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const amount = parseMoney(String(data.get("amount") ?? ""));
    if (!amount) {
      setError("Informe um valor válido em reais.");
      return;
    }
    const splits = data.getAll("members").map((id) => {
      const membershipId = Number.parseInt(String(id), 10);
      if (splitMethod === "equal") return { membership_id: membershipId };
      const raw = String(data.get(`share-${membershipId}`) ?? "");
      if (splitMethod === "percentage") {
        if (!/^\d+(?:[.,]\d{1,4})?$/.test(raw)) return null;
        return { membership_id: membershipId, percent: raw.replace(",", ".") };
      }
      const amountMinor = parseMoney(raw);
      return amountMinor === null
        ? null
        : { membership_id: membershipId, amount_minor: amountMinor };
    });
    if (!splits.length || splits.some((item) => item === null)) {
      setError(
        "Selecione participantes e informe valores válidos para a divisão.",
      );
      return;
    }
    if (
      await mutate(`/households/${householdId}/expenses`, {
        description: data.get("description"),
        category_id: Number.parseInt(String(data.get("category_id")), 10),
        amount_minor: amount,
        incurred_on: data.get("incurred_on"),
        split_method: splitMethod,
        splits,
      })
    ) {
      form.reset();
      setSplitMethod("equal");
    }
  }

  async function registerPayment(
    event: FormEvent<HTMLFormElement>,
    expenseId: number,
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const amount = parseMoney(String(data.get("amount") ?? ""));
    if (!amount) {
      setError("Informe um pagamento válido em reais.");
      return;
    }
    if (
      await mutate(`/expenses/${expenseId}/payments`, {
        payer_id: Number.parseInt(String(data.get("payer_id")), 10),
        amount_minor: amount,
      })
    )
      form.reset();
  }

  async function submitBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const amount = parseMoney(String(new FormData(form).get("amount") ?? ""));
    if (!amount) {
      setError("Informe um orçamento válido em reais.");
      return;
    }
    if (
      await mutate(
        `/households/${householdId}/budgets/${period}`,
        { amount_minor: amount },
        "PUT",
      )
    )
      form.reset();
  }

  const header = (
    <PageHeader
      motif="losango"
      title="Finanças da residência"
      id="finance-title"
    >
      <span className="capitalize">{monthName(period)}</span>
    </PageHeader>
  );

  if (loading)
    return (
      <div className="page">
        {header}
        <div className="tile-wall">
          <section className="tile">
            <Loading label="Carregando finanças…" lines={4} />
          </section>
        </div>
      </div>
    );

  const remaining = summary.budget_total - summary.spent_total;
  return (
    <div className="page">
      {header}
      {canWrite && (
        <SectionNav
          label="Seções de finanças"
          sections={[
            { id: "resumo", label: "Resumo" },
            { id: "lancar", label: "Lançar" },
            { id: "despesas", label: "Despesas" },
            { id: "saldos", label: "Saldos" },
          ]}
        />
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      <div className="tile-wall module-grid">
        <TileSection
          id="resumo"
          className="span-full summary"
          labelledBy="finance-title"
        >
          <p className="statement">
            A casa gastou <strong>{money(summary.spent_total)}</strong> neste
            mês
            {summary.budget_total > 0 ? (
              <>
                , de um orçamento de{" "}
                <strong>{money(summary.budget_total)}</strong>.{" "}
                {remaining < 0 ? "Passou " : "Ainda restam "}
                <strong data-negative={remaining < 0 || undefined}>
                  {money(Math.abs(remaining))}
                </strong>
                {remaining < 0 ? " do previsto." : "."}
              </>
            ) : (
              "."
            )}
          </p>
          {summary.budget_total > 0 ? (
            <TileMeter
              value={summary.spent_total}
              total={summary.budget_total}
            />
          ) : (
            <Text size="sm" c="dimmed">
              Nenhum orçamento definido para este mês.
            </Text>
          )}
        </TileSection>

        <div className="col">
          <TileSection title="Despesas" id="despesas" order={2}>
            {expenses.length === 0 ? (
              <EmptyState>Ainda não há despesas cadastradas.</EmptyState>
            ) : (
              <ul className="rows">
                {expenses.map((expense) => {
                  const status = STATUS[expense.status] ?? {
                    label: "Não paga",
                    color: "barro",
                  };
                  const day = dayParts(expense.incurred_on);
                  return (
                    <li key={expense.id} className="row row-top">
                      <span className="date-tile" aria-hidden="true">
                        <span>
                          <b>{day.day}</b>
                          {day.month}
                        </span>
                      </span>
                      <span className="row-main">
                        <span className="row-title">{expense.description}</span>
                        <span className="row-meta">
                          {expense.category} · {isoDay(expense.incurred_on)} ·
                          pago {money(expense.paid_total)}
                        </span>
                        {expense.splits.length > 0 && (
                          <span className="row-meta">
                            {expense.splits
                              .map(
                                (split) =>
                                  `${split.member_name}: ${money(split.amount_minor)}`,
                              )
                              .join(" · ")}
                          </span>
                        )}
                        {canWrite && expense.status !== "paid" && (
                          <PaymentForm
                            expense={expense}
                            members={members}
                            busy={busy}
                            onPay={registerPayment}
                          />
                        )}
                      </span>
                      <span className="row-end">
                        <strong className="amount">
                          {money(expense.amount_minor)}
                        </strong>
                        <Badge variant="light" color={status.color} size="sm">
                          {status.label}
                        </Badge>
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </TileSection>
        </div>

        <div className="col">
          {canWrite && (
            <TileSection title="Registrar despesa" id="lancar" order={1}>
              <form
                className="stack"
                onSubmit={(event) => void submitExpense(event)}
              >
                <TextInput
                  label="Descrição"
                  name="description"
                  required
                  maxLength={200}
                />
                <div className="pair">
                  <TextInput
                    label="Valor (R$)"
                    name="amount"
                    inputMode="decimal"
                    placeholder="0,00"
                    required
                  />
                  <TextInput
                    label="Data"
                    name="incurred_on"
                    type="date"
                    required
                    defaultValue={localDay(new Date(), timezone)}
                  />
                </div>
                <NativeSelect
                  label="Categoria"
                  name="category_id"
                  required
                  data={categories.map((category) => ({
                    value: String(category.id),
                    label: category.name,
                  }))}
                  description={
                    categories.length
                      ? undefined
                      : "Crie uma categoria primeiro."
                  }
                />
                <NativeSelect
                  label="Método de divisão"
                  name="split_method"
                  value={splitMethod}
                  onChange={(event) =>
                    setSplitMethod(event.currentTarget.value)
                  }
                  data={[
                    { value: "equal", label: "Partes iguais" },
                    { value: "percentage", label: "Percentuais" },
                    { value: "fixed", label: "Valores fixos" },
                  ]}
                />
                <fieldset className="split">
                  <legend>Participantes da divisão</legend>
                  {members.map((member) => (
                    <div key={member.id} className="split-row">
                      <Checkbox
                        name="members"
                        value={member.id}
                        defaultChecked
                        label={member.name}
                      />
                      {splitMethod !== "equal" && (
                        <TextInput
                          aria-label={`${splitMethod === "percentage" ? "Percentual" : "Valor em reais"} de ${member.name}`}
                          name={`share-${member.id}`}
                          inputMode="decimal"
                          placeholder={
                            splitMethod === "percentage" ? "0%" : "0,00"
                          }
                          maxLength={
                            splitMethod === "percentage" ? 10 : undefined
                          }
                          required
                          size="sm"
                          className="split-share"
                        />
                      )}
                    </div>
                  ))}
                  {!members.length && (
                    <Text size="sm" c="dimmed">
                      Nenhum morador encontrado.
                    </Text>
                  )}
                </fieldset>
                <Button
                  type="submit"
                  loading={busy}
                  disabled={categories.length === 0}
                >
                  Salvar despesa
                </Button>
              </form>
            </TileSection>
          )}

          <TileSection title="Saldos dos membros" id="saldos" order={3}>
            {balances.length ? (
              <ul className="rows rows-compact">
                {balances.map((item) => (
                  <li key={item.membership_id} className="row">
                    <span className="row-main">{item.name}</span>
                    <span
                      className="amount"
                      data-negative={item.balance_minor < 0 || undefined}
                    >
                      {money(item.balance_minor)}{" "}
                      <small>
                        {item.balance_minor >= 0 ? "de crédito" : "de dívida"}
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
          </TileSection>

          {canWrite && (
            <TileSection
              title={`Orçamento de ${monthName(period)}`}
              id="orcamento"
              order={4}
            >
              <form
                className="inline-form"
                onSubmit={(event) => void submitBudget(event)}
              >
                <TextInput
                  label="Valor (R$)"
                  name="amount"
                  inputMode="decimal"
                  placeholder="0,00"
                  required
                />
                <Button type="submit" variant="light" loading={busy}>
                  Salvar orçamento
                </Button>
              </form>
            </TileSection>
          )}

          {canWrite && (
            <TileSection title="Nova categoria" id="categorias" order={5}>
              <form
                className="inline-form"
                onSubmit={(event) => void submitCategory(event)}
              >
                <TextInput
                  label="Nome da categoria"
                  name="name"
                  maxLength={80}
                  required
                />
                <Button
                  type="submit"
                  variant="light"
                  loading={busy}
                  leftSection={<IconPlus size={16} aria-hidden="true" />}
                >
                  Criar categoria
                </Button>
              </form>
              {categories.length > 0 && (
                <Group gap={6} mt="sm">
                  {categories.map((category) => (
                    <Badge key={category.id} variant="outline" color="gray">
                      {category.name}
                    </Badge>
                  ))}
                </Group>
              )}
            </TileSection>
          )}
        </div>
      </div>
    </div>
  );
}
