import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
type Chore = {
  id: number;
  title: string;
  description: string;
  category: string;
  recurrence_rule: { frequency: string; time: string } | null;
  is_active: boolean;
};
type Occurrence = {
  id: number;
  title: string;
  due_at: string;
  status: string;
  assigned_name?: string | null;
};

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${url}`, {
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

export default function Chores({
  householdId,
  role,
  timezone = "America/Sao_Paulo",
}: {
  householdId: string;
  role: string;
  timezone?: string;
}) {
  const [chores, setChores] = useState<Chore[]>([]);
  const [occurrences, setOccurrences] = useState<Occurrence[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [generating, setGenerating] = useState(false);
  const writable = role !== "viewer";
  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [items, generated] = await Promise.all([
        request<Chore[]>(`/households/${householdId}/chores`),
        request<Occurrence[]>(`/households/${householdId}/chore-occurrences`),
      ]);
      setChores(items);
      setOccurrences(generated);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Falha ao carregar tarefas.",
      );
    } finally {
      setLoading(false);
    }
  }, [householdId]);
  useEffect(() => {
    void refresh();
  }, [refresh]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccess("");
    const form = event.currentTarget;
    const values = Object.fromEntries(new FormData(form));
    const payload: Record<string, unknown> = {
      title: values.title,
      category: values.category,
      description: values.description,
    };
    if (values.frequency)
      payload.recurrence_rule = {
        frequency: values.frequency,
        time: values.time || "09:00",
      };
    try {
      const headers = await request<{ csrfToken: string }>("/auth/csrf");
      await request(`/households/${householdId}/chores`, {
        method: "POST",
        headers: { "X-CSRFToken": headers.csrfToken },
        body: JSON.stringify(payload),
      });
      form.reset();
      setSuccess("Tarefa criada com sucesso.");
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Não foi possível criar a tarefa.",
      );
    }
  }
  async function complete(id: number) {
    setError("");
    setSuccess("");
    try {
      const csrf = await request<{ csrfToken: string }>("/auth/csrf");
      await request(`/chore-occurrences/${id}/complete`, {
        method: "POST",
        headers: { "X-CSRFToken": csrf.csrfToken },
        body: JSON.stringify({ status: "completed" }),
      });
      setSuccess("Ocorrência concluída.");
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Falha ao concluir.");
    }
  }
  async function updateChore(chore: Chore, patch: Record<string, unknown>) {
    setError("");
    setSuccess("");
    try {
      const csrf = await request<{ csrfToken: string }>("/auth/csrf");
      await request(`/chores/${chore.id}`, {
        method: "PATCH",
        headers: { "X-CSRFToken": csrf.csrfToken },
        body: JSON.stringify(patch),
      });
      setSuccess("Tarefa atualizada.");
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Falha ao atualizar.",
      );
    }
  }
  async function generate() {
    setGenerating(true);
    setError("");
    setSuccess("");
    try {
      const csrf = await request<{ csrfToken: string }>("/auth/csrf");
      for (const chore of chores.filter(
        (item) => item.is_active && item.recurrence_rule,
      ))
        await request(`/chores/${chore.id}/generate-occurrences`, {
          method: "POST",
          headers: { "X-CSRFToken": csrf.csrfToken },
          body: JSON.stringify({ start_date: "today", end_date: "today" }),
        });
      setSuccess("Ocorrências atualizadas.");
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Falha ao gerar ocorrências.",
      );
    } finally {
      setGenerating(false);
    }
  }
  return (
    <section className="module-page">
      <p className="eyebrow">ROTINAS DA CASA</p>
      <h1>Tarefas e rotinas</h1>
      {loading && <p role="status">Carregando tarefas…</p>}
      {error && <p role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}
      {!loading && (
        <>
          <div className="section-heading">
            <h2>Tarefas</h2>
            <span>{chores.length}</span>
          </div>
          {chores.length ? (
            <div className="house-list">
              {chores.map((chore) => (
                <article className="house-card" key={chore.id}>
                  <div>
                    <h3>{chore.title}</h3>
                    <p>
                      {chore.category || "Sem categoria"} ·{" "}
                      {chore.description || "Sem descrição"}
                    </p>
                    <small>
                      {chore.is_active ? "Ativa" : "Inativa"} ·{" "}
                      {chore.recurrence_rule
                        ? `Rotina ${chore.recurrence_rule.frequency} às ${chore.recurrence_rule.time}`
                        : "Tarefa pontual"}
                    </small>
                  </div>
                  {writable && (
                    <div>
                      <button
                        onClick={() => {
                          const title = window.prompt(
                            "Novo título",
                            chore.title,
                          );
                          if (title?.trim()) void updateChore(chore, { title });
                        }}
                      >
                        Editar
                      </button>
                      <button
                        onClick={() =>
                          void updateChore(chore, {
                            is_active: !chore.is_active,
                          })
                        }
                      >
                        {chore.is_active ? "Desativar" : "Ativar"}
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="empty">Ainda não há tarefas cadastradas.</p>
          )}
          <div className="section-heading">
            <h2>Ocorrências</h2>
          </div>
          {occurrences.length ? (
            <div className="house-list">
              {occurrences.map((item) => (
                <article className="house-card" key={item.id}>
                  <div>
                    <h3>{item.title}</h3>
                    <p>
                      {new Intl.DateTimeFormat("pt-BR", {
                        dateStyle: "short",
                        timeStyle: "short",
                        timeZone: timezone,
                      }).format(new Date(item.due_at))}{" "}
                      · {item.assigned_name || "Sem responsável"}
                    </p>
                    <small>
                      {item.status === "completed"
                        ? "Concluída"
                        : item.status === "pending"
                          ? "Pendente"
                          : item.status}
                    </small>
                  </div>
                  {writable && item.status === "pending" && (
                    <button onClick={() => void complete(item.id)}>
                      Concluir
                    </button>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="empty">Nenhuma ocorrência gerada.</p>
          )}
          {writable && (
            <>
              <button disabled={generating} onClick={() => void generate()}>
                {generating ? "Gerando…" : "Gerar ocorrências de hoje"}
              </button>
              <form className="form-stack" onSubmit={create}>
                <h2>Nova tarefa</h2>
                <label>
                  Título
                  <input name="title" required maxLength={120} />
                </label>
                <label>
                  Categoria
                  <input name="category" maxLength={80} />
                </label>
                <label>
                  Descrição
                  <textarea name="description" maxLength={4000} />
                </label>
                <label>
                  Recorrência
                  <select name="frequency" defaultValue="">
                    <option value="">Tarefa sem repetição</option>
                    <option value="daily">Diária</option>
                    <option value="weekly">Semanal</option>
                    <option value="monthly">Mensal</option>
                  </select>
                </label>
                <label>
                  Hora local da rotina
                  <input type="time" name="time" defaultValue="09:00" />
                </label>
                <button>Criar tarefa</button>
              </form>
            </>
          )}
        </>
      )}
    </section>
  );
}
