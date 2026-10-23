import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const localDate = new Date();
const localPeriod = `${localDate.getFullYear()}-${String(localDate.getMonth() + 1).padStart(2, "0")}`;
const localDateString = `${localPeriod}-${String(localDate.getDate()).padStart(2, "0")}`;
type Category = { id: number; name: string; kind: string };
type Member = { id: number; name: string; role: string };
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
type Summary = { spent_total: number; budget_total: number };

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.detail ??
        Object.values(data).flat().join(" ") ??
        "Falha na solicitação.",
    );
  return data as T;
}

function money(cents: number) {
  const absolute = Math.abs(cents);
  const major = String(Math.trunc(absolute / 100)).replace(
    /\B(?=(\d{3})+(?!\d))/g,
    ".",
  );
  return `R$ ${cents < 0 ? "-" : ""}${major},${String(absolute % 100).padStart(2, "0")}`;
}

function parseMoney(value: string): number | null {
  const normalized = value
    .trim()
    .replace(/^R\$\s*/, "")
    .replace(/\./g, "")
    .replace(",", ".");
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  const cents = `${fraction}00`.slice(0, 2);
  const result = `${whole}${cents}`.replace(/^0+(?=\d)/, "");
  if (result.length > 15) return null;
  return result
    .split("")
    .reduce((amount, digit) => amount * 10 + digit.charCodeAt(0) - 48, 0);
}

export default function Finance({
  householdId,
  role,
}: {
  householdId: string;
  role: string;
}) {
  const canWrite = role === "owner" || role === "member";
  const [categories, setCategories] = useState<Category[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [summary, setSummary] = useState<Summary>({
    spent_total: 0,
    budget_total: 0,
  });
  const [balances, setBalances] = useState<
    { membership_id: number; name: string; balance_minor: number }[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [splitMethod, setSplitMethod] = useState("equal");
  const [period] = useState(localPeriod);

  const refresh = useCallback(async () => {
    setLoading(true);
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
          request<typeof balances>(`/households/${householdId}/settlements`),
        ]);
      setCategories(categoryRows);
      setMembers(memberRows);
      setExpenses(expenseRows);
      setSummary(summaryRow);
      setBalances(balanceRows);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Não foi possível carregar as finanças.",
      );
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
    setNotice("");
    try {
      const csrf = await request<{ csrfToken: string }>("/auth/csrf");
      await request(path, {
        method,
        headers: { "X-CSRFToken": csrf.csrfToken },
        body: JSON.stringify(payload),
      });
      setNotice("Alterações salvas com sucesso.");
      await refresh();
      return true;
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Não foi possível salvar.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submitCategory(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const formElement = event.currentTarget;
    if (
      await mutate(`/finance/categories`, {
        household_id: householdId,
        name: form.get("name"),
      })
    )
      formElement.reset();
  }

  async function submitExpense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const amount = parseMoney(String(form.get("amount") ?? ""));
    if (!amount) {
      setError("Informe um valor válido em reais.");
      return;
    }
    const selected = Array.from(form.getAll("members")).map((id) => {
      const membershipId = Number.parseInt(String(id), 10);
      if (splitMethod === "equal") return { membership_id: membershipId };
      const raw = String(form.get(`share-${membershipId}`) ?? "");
      if (splitMethod === "percentage") {
        if (!/^\d+(?:[.,]\d{1,4})?$/.test(raw)) return null;
        return {
          membership_id: membershipId,
          percent: raw.replace(",", "."),
        };
      }
      const amountMinor = parseMoney(raw);
      return amountMinor === null
        ? null
        : { membership_id: membershipId, amount_minor: amountMinor };
    });
    if (!selected.length || selected.some((item) => item === null)) {
      setError(
        "Selecione participantes e informe valores válidos para a divisão.",
      );
      return;
    }
    const formElement = event.currentTarget;
    if (
      await mutate(`/households/${householdId}/expenses`, {
        description: form.get("description"),
        category_id: Number.parseInt(String(form.get("category_id")), 10),
        amount_minor: amount,
        incurred_on: form.get("incurred_on"),
        split_method: splitMethod,
        splits: selected,
      })
    )
      formElement.reset();
  }

  async function registerPayment(
    event: FormEvent<HTMLFormElement>,
    expenseId: number,
  ) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const amount = parseMoney(String(form.get("amount") ?? ""));
    if (!amount) {
      setError("Informe um pagamento válido em reais.");
      return;
    }
    const formElement = event.currentTarget;
    if (
      await mutate(`/expenses/${expenseId}/payments`, {
        payer_id: Number.parseInt(String(form.get("payer_id")), 10),
        amount_minor: amount,
      })
    )
      formElement.reset();
  }

  async function submitBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const amount = parseMoney(String(form.get("amount") ?? ""));
    if (!amount) {
      setError("Informe um orçamento válido em reais.");
      return;
    }
    const formElement = event.currentTarget;
    if (
      await mutate(
        `/households/${householdId}/budgets/${period}`,
        { amount_minor: amount },
        "PUT",
      )
    )
      formElement.reset();
  }

  if (loading) return <p role="status">Carregando finanças…</p>;
  return (
    <section className="finance-panel" aria-labelledby="finance-title">
      <h1 id="finance-title">Finanças da residência</h1>
      {error && (
        <p role="alert" className="message">
          {error}
        </p>
      )}
      {notice && (
        <p role="status" className="message">
          {notice}
        </p>
      )}
      <div className="finance-summary">
        <p>
          Gastos do mês: <strong>{money(summary.spent_total)}</strong>
        </p>
        <p>
          Orçamento do mês: <strong>{money(summary.budget_total)}</strong>
        </p>
      </div>
      {canWrite && (
        <form className="form-stack finance-form" onSubmit={submitCategory}>
          <h2>Nova categoria</h2>
          <label>
            Nome da categoria
            <input name="name" maxLength={80} required />
          </label>
          <button disabled={busy}>Criar categoria</button>
        </form>
      )}
      {canWrite && (
        <form className="form-stack finance-form" onSubmit={submitExpense}>
          <h2>Registrar despesa</h2>
          <label>
            Descrição
            <input name="description" required maxLength={200} />
          </label>
          <label>
            Categoria
            <select name="category_id" required>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Valor (R$)
            <input
              name="amount"
              inputMode="decimal"
              placeholder="0,00"
              required
            />
          </label>
          <label>
            Data
            <input
              name="incurred_on"
              type="date"
              required
              defaultValue={localDateString}
            />
          </label>
          <label>
            Método de divisão
            <select
              name="split_method"
              value={splitMethod}
              onChange={(event) => setSplitMethod(event.target.value)}
            >
              <option value="equal">Partes iguais</option>
              <option value="percentage">Percentuais</option>
              <option value="fixed">Valores fixos</option>
            </select>
          </label>
          <fieldset>
            <legend>Participantes da divisão</legend>
            {members.map((member) => (
              <label key={member.id}>
                <input
                  type="checkbox"
                  name="members"
                  value={member.id}
                  defaultChecked
                />
                {member.name}
                {splitMethod !== "equal" && (
                  <input
                    aria-label={`${splitMethod === "percentage" ? "Percentual" : "Valor em reais"} de ${member.name}`}
                    name={`share-${member.id}`}
                    inputMode="decimal"
                    placeholder={
                      splitMethod === "percentage" ? "0,0000%" : "0,00"
                    }
                    maxLength={splitMethod === "percentage" ? 10 : undefined}
                    required
                  />
                )}
              </label>
            ))}
          </fieldset>
          <button disabled={busy || categories.length === 0}>
            Salvar despesa
          </button>
        </form>
      )}
      {canWrite && (
        <form className="form-stack finance-form" onSubmit={submitBudget}>
          <h2>Orçamento do mês · {period}</h2>
          <label>
            Valor (R$)
            <input
              name="amount"
              inputMode="decimal"
              placeholder="0,00"
              required
            />
          </label>
          <button disabled={busy}>Salvar orçamento</button>
        </form>
      )}
      <h2>Despesas</h2>
      {expenses.length === 0 ? (
        <p className="empty">Ainda não há despesas cadastradas.</p>
      ) : (
        <div className="house-list">
          {expenses.map((expense) => (
            <article className="house-card" key={expense.id}>
              <div>
                <h3>{expense.description}</h3>
                <p>
                  {expense.category} · {expense.incurred_on} ·{" "}
                  {money(expense.amount_minor)}
                </p>
                <p>
                  Pago: {money(expense.paid_total)} · Status:{" "}
                  {expense.status === "paid"
                    ? "paga"
                    : expense.status === "partial"
                      ? "parcialmente paga"
                      : "não paga"}
                </p>
                <p>
                  {expense.splits
                    .map(
                      (split) =>
                        `${split.member_name}: ${money(split.amount_minor)}`,
                    )
                    .join(" · ")}
                </p>
                {canWrite && expense.status !== "paid" && (
                  <form
                    onSubmit={(event) => registerPayment(event, expense.id)}
                  >
                    <label>
                      Registrar pagamento (R$)
                      <input
                        name="amount"
                        inputMode="decimal"
                        required
                        placeholder="0,00"
                      />
                    </label>
                    <label>
                      Pago por
                      <select name="payer_id">
                        {members.map((member) => (
                          <option key={member.id} value={member.id}>
                            {member.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <button disabled={busy}>Registrar pagamento</button>
                  </form>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
      <h2>Saldos dos membros</h2>
      <ul>
        {balances.map((item) => (
          <li key={item.membership_id}>
            {item.name}: {money(item.balance_minor)}{" "}
            {item.balance_minor >= 0 ? "de crédito" : "de dívida"}
          </li>
        ))}
      </ul>
    </section>
  );
}
