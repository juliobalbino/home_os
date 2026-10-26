import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  Badge,
  Button,
  Group,
  NativeSelect,
  Text,
  TextInput,
  Textarea,
} from "@mantine/core";
import {
  IconCalendarPlus,
  IconPencil,
  IconPlayerPause,
  IconPlayerPlay,
} from "@tabler/icons-react";
import { list, reason, request, send } from "../../lib/api";
import type { Occurrence } from "../../lib/api";
import { dateTime } from "../../lib/format";
import { useToast } from "../../ui/Toaster";
import {
  EmptyState,
  ErrorNote,
  FlipTile,
  Loading,
  PageHeader,
  TileSection,
} from "../../ui/parts";

type Chore = {
  id: number;
  title: string;
  description: string;
  category: string;
  recurrence_rule: { frequency: string; time: string } | null;
  is_active: boolean;
};

const FREQUENCY: Record<string, string> = {
  daily: "Diária",
  weekly: "Semanal",
  monthly: "Mensal",
};

function ChoreRow({
  chore,
  writable,
  onUpdate,
}: {
  chore: Chore;
  writable: boolean;
  onUpdate: (chore: Chore, patch: Record<string, unknown>) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(chore.title);
  const routine = chore.recurrence_rule;
  return (
    <li className="row row-top" data-inactive={!chore.is_active || undefined}>
      <span className="row-main">
        {editing ? (
          <form
            className="inline-edit"
            onSubmit={async (event) => {
              event.preventDefault();
              if (
                title.trim() &&
                (await onUpdate(chore, { title: title.trim() }))
              )
                setEditing(false);
            }}
          >
            <TextInput
              label={`Novo título de ${chore.title}`}
              value={title}
              maxLength={120}
              onChange={(event) => setTitle(event.currentTarget.value)}
              size="sm"
              autoFocus
            />
            <Group gap="xs">
              <Button type="submit" size="xs">
                Salvar
              </Button>
              <Button
                size="xs"
                variant="subtle"
                color="gray"
                onClick={() => {
                  setTitle(chore.title);
                  setEditing(false);
                }}
              >
                Cancelar
              </Button>
            </Group>
          </form>
        ) : (
          <>
            <span className="row-title">{chore.title}</span>
            <span className="row-meta">
              {[chore.category || "Sem categoria", chore.description]
                .filter(Boolean)
                .join(" · ")}
            </span>
          </>
        )}
        <span className="row-tags">
          <Badge
            variant="light"
            color={chore.is_active ? "azulejo" : "gray"}
            size="sm"
          >
            {chore.is_active ? "Ativa" : "Inativa"}
          </Badge>
          <Badge variant="outline" color="gray" size="sm">
            {routine
              ? `${FREQUENCY[routine.frequency] ?? routine.frequency} às ${routine.time}`
              : "Tarefa pontual"}
          </Badge>
        </span>
      </span>
      {writable && !editing && (
        <span className="row-actions">
          <Button
            size="xs"
            variant="subtle"
            leftSection={<IconPencil size={14} aria-hidden="true" />}
            onClick={() => setEditing(true)}
          >
            Editar
          </Button>
          <Button
            size="xs"
            variant="subtle"
            color={chore.is_active ? "gray" : "azulejo"}
            leftSection={
              chore.is_active ? (
                <IconPlayerPause size={14} aria-hidden="true" />
              ) : (
                <IconPlayerPlay size={14} aria-hidden="true" />
              )
            }
            onClick={() =>
              void onUpdate(chore, { is_active: !chore.is_active })
            }
          >
            {chore.is_active ? "Desativar" : "Ativar"}
          </Button>
        </span>
      )}
    </li>
  );
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
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [finishing, setFinishing] = useState<number | null>(null);
  const toast = useToast();
  const writable = role !== "viewer";

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [items, generated] = await Promise.all([
        request<Chore[]>(`/households/${householdId}/chores`),
        request<Occurrence[]>(`/households/${householdId}/chore-occurrences`),
      ]);
      setChores(list<Chore>(items));
      setOccurrences(list<Occurrence>(generated));
    } catch (cause) {
      setError(reason(cause, "Falha ao carregar tarefas."));
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
    setSaving(true);
    try {
      await send(`/households/${householdId}/chores`, payload);
      form.reset();
      toast.success("Tarefa criada com sucesso.");
      await refresh();
    } catch (cause) {
      setError(reason(cause, "Não foi possível criar a tarefa."));
    } finally {
      setSaving(false);
    }
  }

  async function complete(id: number) {
    setError("");
    setFinishing(id);
    try {
      await send(`/chore-occurrences/${id}/complete`, { status: "completed" });
      setOccurrences((rows) =>
        rows.map((row) =>
          row.id === id ? { ...row, status: "completed" } : row,
        ),
      );
      toast.success("Ocorrência concluída.");
      await refresh();
    } catch (cause) {
      setError(reason(cause, "Falha ao concluir."));
    } finally {
      setFinishing(null);
    }
  }

  async function updateChore(chore: Chore, patch: Record<string, unknown>) {
    setError("");
    try {
      await send(`/chores/${chore.id}`, patch, "PATCH");
      toast.success("Tarefa atualizada.");
      await refresh();
      return true;
    } catch (cause) {
      setError(reason(cause, "Falha ao atualizar."));
      return false;
    }
  }

  async function generate() {
    setGenerating(true);
    setError("");
    try {
      for (const chore of chores.filter(
        (item) => item.is_active && item.recurrence_rule,
      ))
        await send(`/chores/${chore.id}/generate-occurrences`, {
          start_date: "today",
          end_date: "today",
        });
      toast.success("Ocorrências atualizadas.");
      await refresh();
    } catch (cause) {
      setError(reason(cause, "Falha ao gerar ocorrências."));
    } finally {
      setGenerating(false);
    }
  }

  const now = new Date();
  const pending = occurrences.filter(
    (item) => item.status === "pending",
  ).length;
  const ordered = [...occurrences].sort(
    (a, b) =>
      Number(a.status !== "pending") - Number(b.status !== "pending") ||
      a.due_at.localeCompare(b.due_at),
  );

  return (
    <div className="page">
      <PageHeader
        motif="catavento"
        title="Tarefas e rotinas"
        aside={
          writable &&
          !loading && (
            <Button
              variant="light"
              loading={generating}
              onClick={() => void generate()}
              leftSection={<IconCalendarPlus size={16} aria-hidden="true" />}
            >
              Criar as tarefas de hoje
            </Button>
          )
        }
      >
        {loading
          ? "Rotinas da casa"
          : `${pending} pendente${pending === 1 ? "" : "s"}`}
      </PageHeader>
      {error && <ErrorNote>{error}</ErrorNote>}
      {loading ? (
        <div className="tile-wall">
          <section className="tile">
            <Loading label="Carregando tarefas…" lines={4} />
          </section>
        </div>
      ) : (
        <div className="tile-wall module-grid">
          <div className="col">
            <TileSection title="Para fazer" id="ocorrencias">
              {ordered.length ? (
                <ul className="rows">
                  {ordered.map((item) => {
                    const done = item.status === "completed";
                    const late = !done && new Date(item.due_at) < now;
                    return (
                      <li
                        key={item.id}
                        className="row"
                        data-done={done || undefined}
                      >
                        <FlipTile done={done} motif="catavento" />
                        <span className="row-main">
                          <span className="row-title">{item.title}</span>
                          <span className="row-meta">
                            {dateTime(item.due_at, timezone)} ·{" "}
                            {item.assigned_name || "Sem responsável"}
                          </span>
                        </span>
                        {writable && item.status === "pending" ? (
                          <Button
                            size="sm"
                            variant={late ? "filled" : "light"}
                            color={late ? "ocre.5" : "azulejo"}
                            loading={finishing === item.id}
                            onClick={() => void complete(item.id)}
                          >
                            Concluir
                          </Button>
                        ) : (
                          <Badge
                            variant="light"
                            color={done ? "azulejo" : late ? "ocre" : "gray"}
                          >
                            {done
                              ? "Concluída"
                              : late
                                ? "Atrasada"
                                : item.status === "pending"
                                  ? "Pendente"
                                  : item.status}
                          </Badge>
                        )}
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState>
                  Nenhuma ocorrência gerada.{" "}
                  {writable &&
                    "Crie uma rotina e use “Criar as tarefas de hoje”."}
                </EmptyState>
              )}
            </TileSection>

            <TileSection title="Tarefas" id="tarefas-cadastradas">
              {chores.length ? (
                <ul className="rows">
                  {chores.map((chore) => (
                    <ChoreRow
                      key={`${chore.id}-${chore.title}`}
                      chore={chore}
                      writable={writable}
                      onUpdate={updateChore}
                    />
                  ))}
                </ul>
              ) : (
                <EmptyState>Ainda não há tarefas cadastradas.</EmptyState>
              )}
            </TileSection>
          </div>
          <div className="col">
            {writable ? (
              <TileSection title="Nova tarefa" id="nova-tarefa">
                <form className="stack" onSubmit={create}>
                  <TextInput
                    label="Título"
                    name="title"
                    required
                    maxLength={120}
                  />
                  <TextInput
                    label="Categoria"
                    name="category"
                    maxLength={80}
                    description="Opcional"
                  />
                  <Textarea
                    label="Descrição"
                    name="description"
                    maxLength={4000}
                    autosize
                    minRows={2}
                    description="Opcional"
                  />
                  <div className="pair">
                    <NativeSelect
                      label="Recorrência"
                      name="frequency"
                      defaultValue=""
                      data={[
                        { value: "", label: "Sem repetição" },
                        { value: "daily", label: "Diária" },
                        { value: "weekly", label: "Semanal" },
                        { value: "monthly", label: "Mensal" },
                      ]}
                    />
                    <TextInput
                      label="Hora local da rotina"
                      type="time"
                      name="time"
                      defaultValue="09:00"
                    />
                  </div>
                  <Button type="submit" loading={saving}>
                    Criar tarefa
                  </Button>
                </form>
              </TileSection>
            ) : (
              <TileSection>
                <Text size="sm" c="dimmed">
                  Você tem acesso de visualização: acompanha as tarefas, mas não
                  cria nem conclui.
                </Text>
              </TileSection>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
