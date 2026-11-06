import { useEffect, useState } from "react";
import {
  Anchor,
  Badge,
  Card,
  Button,
  FileInput,
  Group,
  Modal,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconPhoto, IconSparkles } from "@tabler/icons-react";
import { AnimatePresence, motion } from "motion/react";
import { apiOrigin, apiUrl, reason, request, send } from "../../lib/api";
import { TileMark } from "../../ui/Tile";
import { ErrorNote } from "../../ui/parts";

type Status = {
  enabled: boolean;
  connected: boolean;
  status?: string;
  configuration?: string;
  can_disconnect?: boolean;
};
type DisconnectResponse = {
  disconnected: boolean;
  revocation_confirmed: boolean;
};
type Result = {
  text: string;
  requires_confirmation: boolean;
  actions?: ActionProposal[];
  applied?: Array<{ tool: string; summary: string }>;
  issues?: Array<{ tool: string; message: string }>;
};
type ActionProposal = {
  proposal_id: string;
  kind: string;
  title: string;
  summary: string;
  details: {
    list?: { name?: string; status?: string };
    items?: Array<{
      product_name?: string | null;
      free_text_name?: string | null;
      quantity?: string | number;
      unit?: string;
      status?: string;
    }>;
  };
  expires_at: string;
  localStatus?:
    | "pending"
    | "completed"
    | "cancelled"
    | "stale"
    | "expired"
    | "error";
  feedback?: string;
};
type Pairing = { pairing_id: string; pairing_code: string; expires_at: string };
type PairingStatus = {
  status:
    | "pending"
    | "claimed"
    | "completing"
    | "completed"
    | "expired"
    | "cancelled"
    | "failed";
  expires_at: string;
};

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

function statusText(status: Status | null) {
  if (!status) return "Verificando o assistente…";
  if (status.connected) return "Conectado à sua conta ChatGPT";
  if (status.status === "consent_required")
    return "O consentimento ainda está pendente. Conecte novamente e aprove o acesso no navegador.";
  if (status.status === "pending_configuration")
    return "Conexão concluída; a configuração do Assistente ainda está pendente.";
  switch (status.configuration) {
    case "disabled":
      return "O Assistente está desativado no momento. Peça ajuda à pessoa administradora da casa para ativá-lo.";
    case "missing_or_invalid_encryption_key":
      return "O Assistente está indisponível no momento. Peça ajuda à pessoa administradora da casa.";
    case "credential_unavailable":
      return "O Assistente está indisponível no momento. Peça ajuda à pessoa administradora da casa.";
  }
  return status.enabled
    ? "Conecte sua conta ChatGPT usando o botão Conectar ChatGPT."
    : "A conexão com o ChatGPT ainda não foi concluída. Peça ajuda à pessoa administradora da casa.";
}

const localizedStatus: Record<string, string> = {
  active: "Ativa",
  pending: "Pendente",
  checked: "Separado",
  completed: "Concluído",
};

function AssistantActionProposal({
  proposal,
  onAction,
  busy,
}: {
  proposal: ActionProposal;
  onAction: (confirm: boolean) => void;
  busy: boolean;
}) {
  const isDelete = proposal.kind === "delete_shopping_list";
  const terminal = proposal.localStatus && proposal.localStatus !== "pending";
  return (
    <Card
      withBorder
      role="group"
      aria-label={proposal.title}
      mt="md"
      padding="md"
    >
      <Title order={4}>{proposal.title}</Title>
      <Text>{proposal.summary}</Text>
      {isDelete && (
        <>
          <Text fw={700} mt="sm">
            Prévia da lista:
          </Text>
          <Text fw={700}>
            {proposal.details.list?.name ?? "Lista sem nome"}
          </Text>
          {proposal.details.list?.status && (
            <Text size="sm">
              Status da lista:{" "}
              {localizedStatus[proposal.details.list.status] ?? "Outro"}
            </Text>
          )}
          <ul aria-label="Itens da lista">
            {(proposal.details.items ?? []).map((item, index) => (
              <li key={index}>
                <Text component="span">
                  {item.product_name || item.free_text_name || "Item sem nome"}
                </Text>
                {" — "}
                <Text component="span">
                  {item.quantity ?? "—"} {item.unit ?? ""}
                </Text>
                {" — "}
                <Text component="span">
                  {localizedStatus[item.status ?? ""] ?? "Outro"} (
                  {item.status ?? "desconhecido"})
                </Text>
              </li>
            ))}
          </ul>
        </>
      )}
      <Text role="status" aria-live="polite" mt="sm">
        {proposal.feedback ??
          (terminal
            ? ""
            : "Aguardando sua confirmação para aplicar esta ação.")}
      </Text>
      {!terminal && (
        <Group mt="sm">
          <Button
            color="red"
            onClick={() => onAction(true)}
            loading={busy}
            disabled={busy}
          >
            {isDelete ? "Confirmar exclusão" : "Confirmar ação"}
          </Button>
          <Button
            variant="default"
            onClick={() => onAction(false)}
            loading={busy}
            disabled={busy}
          >
            Cancelar proposta
          </Button>
        </Group>
      )}
    </Card>
  );
}

export default function Assistant({
  householdId,
  role,
  compact = false,
}: {
  householdId: string;
  role: string;
  /** Starts folded to one row so it does not crowd the first screen. */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(!compact);
  const [status, setStatus] = useState<Status | null>(null);
  const [text, setText] = useState("");
  const [image, setImage] = useState<File | null>(null);
  const [imageData, setImageData] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [disconnectError, setDisconnectError] = useState("");
  const [disconnectMessage, setDisconnectMessage] = useState("");
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const [pairingState, setPairingState] = useState("");
  const [pairingError, setPairingError] = useState("");
  const [pairingBusy, setPairingBusy] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState("");
  const [actionBusy, setActionBusy] = useState<string | null>(null);

  useEffect(() => {
    request<Status>("/assistant/status")
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, connected: false }));
  }, []);

  useEffect(() => {
    setResult(null);
    setError("");
    setText("");
    setImage(null);
    setImageData("");
  }, [householdId]);

  useEffect(() => {
    if (!pairing) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const current = await request<PairingStatus>(
          `/assistant/connect/pairings/${encodeURIComponent(pairing.pairing_id)}`,
        );
        if (!active) return;
        setPairingState(current.status);
        if (current.status === "completed") {
          const refreshed = await request<Status>("/assistant/status");
          if (!active) return;
          setStatus({
            ...refreshed,
          });
          setPairing(null);
          setConnectOpen(false);
          setPairingState(
            refreshed.status === "consent_required"
              ? "consent_required"
              : refreshed.status === "pending_configuration"
                ? "pending_configuration"
                : refreshed.connected
                  ? "connected"
                  : "",
          );
          return;
        }
        if (["expired", "cancelled", "failed"].includes(current.status)) {
          setPairingError(
            current.status === "expired"
              ? "O código expirou."
              : current.status === "cancelled"
                ? "A conexão foi cancelada."
                : "Não foi possível concluir a conexão.",
          );
          return;
        }
        timer = setTimeout(poll, 1000);
      } catch {
        if (active) {
          setPairingError(
            "Não foi possível verificar a conexão. Tente novamente.",
          );
        }
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [pairing]);

  async function startPairing(forceRetry = false) {
    setConnectOpen(true);
    if (pairing && !forceRetry) return;
    if (forceRetry) setPairing(null);
    setPairingBusy(true);
    setPairingError("");
    setPairingState("");
    try {
      const created = await send<Pairing>("/assistant/connect/pairings", {});
      setPairing(created);
    } catch (cause) {
      setPairingError(reason(cause, "Não foi possível iniciar a conexão."));
    } finally {
      setPairingBusy(false);
    }
  }

  async function copy(value: string, label: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopyFeedback(`${label} copiado.`);
    } catch {
      setCopyFeedback(`Não foi possível copiar ${label.toLowerCase()}.`);
    }
  }

  function pick(file: File | null) {
    setError("");
    setImage(null);
    setImageData("");
    if (!file) return;
    if (file.size > 5 * 1024 * 1024 || !IMAGE_TYPES.includes(file.type)) {
      setError("Use uma imagem JPEG, PNG ou WebP de até 5 MB.");
      return;
    }
    setImage(file);
    const reader = new FileReader();
    reader.onload = () => setImageData(String(reader.result));
    reader.readAsDataURL(file);
  }

  async function submit() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      setResult(
        await send<Result>(`/households/${householdId}/assistant`, {
          text,
          request_id: crypto.randomUUID(),
          ...(imageData ? { image_data: imageData } : {}),
        }),
      );
    } catch (cause) {
      setError(reason(cause, "Não foi possível concluir o pedido."));
    } finally {
      setBusy(false);
    }
  }

  async function respondToProposal(proposal: ActionProposal, confirm: boolean) {
    setActionBusy(proposal.proposal_id);
    try {
      await send(
        `/households/${householdId}/assistant/actions/${encodeURIComponent(proposal.proposal_id)}`,
        { confirm },
      );
      setResult((current) =>
        current
          ? {
              ...current,
              actions: current.actions?.map((item) =>
                item.proposal_id === proposal.proposal_id
                  ? {
                      ...item,
                      localStatus: confirm ? "completed" : "cancelled",
                      feedback: confirm
                        ? proposal.kind === "delete_shopping_list"
                          ? "Exclusão concluída com sucesso."
                          : "Ação concluída com sucesso."
                        : "Proposta cancelada.",
                    }
                  : item,
              ),
            }
          : current,
      );
    } catch (cause) {
      const code = (cause as Error & { status?: number }).status;
      const localStatus =
        code === 409 ? "stale" : code === 410 ? "expired" : "error";
      const feedback =
        code === 409
          ? "A proposta está desatualizada e não foi aplicada. Solicite uma nova análise."
          : code === 410
            ? "A proposta expirou e não foi aplicada. Solicite uma nova análise."
            : "Não foi possível concluir a ação. A proposta não foi confirmada.";
      setResult((current) =>
        current
          ? {
              ...current,
              actions: current.actions?.map((item) =>
                item.proposal_id === proposal.proposal_id
                  ? { ...item, localStatus, feedback }
                  : item,
              ),
            }
          : current,
      );
    } finally {
      setActionBusy(null);
    }
  }

  async function disconnect() {
    setDisconnectBusy(true);
    setDisconnectError("");
    setDisconnectMessage("");
    try {
      const response = await send<DisconnectResponse>(
        "/assistant/disconnect",
        {},
      );
      if (response.disconnected) {
        setStatus((current) =>
          current
            ? {
                ...current,
                connected: false,
                can_disconnect: false,
                status: response.revocation_confirmed
                  ? "disconnected"
                  : "revocation_unconfirmed",
              }
            : {
                enabled: true,
                connected: false,
                can_disconnect: false,
                status: response.revocation_confirmed
                  ? "disconnected"
                  : "revocation_unconfirmed",
              },
        );
      }
      setDisconnectMessage(
        response.revocation_confirmed
          ? "Acesso do Home OS desconectado com sucesso."
          : "As credenciais locais do Home OS foram removidas, mas a revogação remota não foi confirmada.",
      );
      setDisconnectOpen(false);
      try {
        const refreshed = await request<Status>("/assistant/status");
        setStatus(refreshed);
      } catch {
        // The successful disconnect response is authoritative; keep local state.
      }
    } catch (cause) {
      setDisconnectError(
        reason(
          cause,
          "Não foi possível desconectar o ChatGPT. Tente novamente.",
        ),
      );
    } finally {
      setDisconnectBusy(false);
    }
  }

  const connected = Boolean(status?.connected);
  return (
    <section aria-labelledby="assistant-title" className="tile assistant">
      <div className="tile-head">
        <TileMark motif="olho" size={28} />
        <Title order={2} id="assistant-title">
          Assistente da casa
        </Title>
        <Badge variant="dot" color={connected ? "azulejo" : "gray"} ml="auto">
          {connected ? "Ativo" : "Inativo"}
        </Badge>
      </div>
      <Text size="sm" c="dimmed" className="assistant-status">
        {statusText(status)}
      </Text>
      {status?.enabled && !connected && (
        <Button
          onClick={() => {
            setPairingError("");
            setPairingState("");
            void startPairing();
          }}
          loading={pairingBusy}
        >
          Conectar ChatGPT
        </Button>
      )}
      <Modal
        opened={connectOpen}
        onClose={() => setConnectOpen(false)}
        title="Conectar ChatGPT"
        size="lg"
      >
        {pairingBusy && (
          <Text role="status" size="sm" mb="sm">
            Iniciando conexão…
          </Text>
        )}
        {pairing && (
          <>
            <Text size="sm" mb="sm">
              Siga estas etapas para conectar sua conta:
            </Text>
            <ol>
              <li>Copie a origem da API do Home OS.</li>
              <li>Baixe o auxiliar do Windows.</li>
              <li>
                Execute <code>python homeos_chatgpt_connect.py</code>.
              </li>
              <li>Digite o código de pareamento no auxiliar.</li>
              <li>
                No navegador, selecione sua conta ChatGPT. Ao reconectar, use a
                mesma conta da conexão anterior. Conclua o login e, quando
                solicitado, autorize o acesso.
              </li>
            </ol>
            <Text size="sm" mb="sm">
              O código de uso único expira em 5 minutos. Isso não desconecta
              suas sessões do site do ChatGPT.
            </Text>
            <Group mb="sm">
              <Button onClick={() => void copy(apiOrigin(), "Origem da API")}>
                Copiar origem da API
              </Button>
              <Text size="sm" c="dimmed">
                {apiOrigin()}
              </Text>
              <Button
                component="a"
                href={apiUrl("/assistant/connect/helper")}
                download
              >
                Baixar auxiliar do Windows
              </Button>
            </Group>
            <Group>
              <Text fw={700} aria-label="Código de pareamento">
                {pairing.pairing_code}
              </Text>
              <Button
                variant="light"
                onClick={() => void copy(pairing.pairing_code, "Código")}
              >
                Copiar código
              </Button>
            </Group>
            <Text role="status" aria-live="polite" size="sm" mt="sm">
              {copyFeedback ||
                (pairingState === "claimed"
                  ? "Auxiliar conectado; aguardando conclusão…"
                  : pairingState === "completing"
                    ? "Finalizando a conexão…"
                    : "Aguardando o auxiliar…")}
            </Text>
          </>
        )}
        {pairingError && <ErrorNote>{pairingError}</ErrorNote>}
        {pairingState === "consent_required" && (
          <Text role="status">
            Conexão concluída, mas é necessário conceder consentimento
            novamente.
          </Text>
        )}
        {pairingState === "pending_configuration" && (
          <Text role="status">
            Conexão concluída; a configuração ainda está pendente.
          </Text>
        )}
        {pairingState === "connected" && (
          <Text role="status">ChatGPT conectado com sucesso.</Text>
        )}
        {pairingError && (
          <Button
            mt="md"
            onClick={() => {
              setPairingError("");
              setPairingState("");
              void startPairing(true);
            }}
          >
            Tentar novamente
          </Button>
        )}
      </Modal>
      {status?.can_disconnect && (
        <Button
          variant="light"
          color="red"
          onClick={() => {
            setDisconnectError("");
            setDisconnectOpen(true);
          }}
        >
          Desconectar ChatGPT
        </Button>
      )}
      {disconnectMessage && (
        <Text role="status" size="sm">
          {disconnectMessage}
        </Text>
      )}
      <Modal
        opened={disconnectOpen}
        onClose={() => {
          if (!disconnectBusy) setDisconnectOpen(false);
        }}
        title="Desconectar ChatGPT"
        closeOnClickOutside={!disconnectBusy}
        closeOnEscape={!disconnectBusy}
      >
        <Text size="sm" mb="md">
          Remover o acesso do Home OS? Isso sempre remove as credenciais locais
          do Home OS. A revogação no provedor pode não estar disponível ou
          confirmada para credenciais transferidas à VM. Você continuará
          conectado às sessões do site do ChatGPT e em outros dispositivos. Para
          conectar novamente, use Conectar ChatGPT e siga as etapas mostradas.
        </Text>
        {disconnectError && <ErrorNote>{disconnectError}</ErrorNote>}
        <Group justify="flex-end" mt="lg">
          <Button
            variant="default"
            disabled={disconnectBusy}
            onClick={() => setDisconnectOpen(false)}
          >
            Cancelar
          </Button>
          <Button
            color="red"
            loading={disconnectBusy}
            onClick={() => void disconnect()}
          >
            Confirmar desconexão
          </Button>
        </Group>
      </Modal>
      {connected && (
        <Anchor
          href="https://chatgpt.com/settings/usage"
          target="_blank"
          rel="noreferrer"
          size="sm"
          className="assistant-usage"
        >
          Consultar uso e limites no ChatGPT{" "}
          <IconExternalLink size={14} aria-hidden="true" />
        </Anchor>
      )}
      {connected && role !== "viewer" && compact && (
        <Group>
          <Button
            variant="light"
            aria-expanded={open}
            onClick={() => setOpen((value) => !value)}
          >
            {open ? "Fechar assistente" : "Abrir assistente"}
          </Button>
        </Group>
      )}
      {connected && role !== "viewer" && open && (
        <div className="assistant-form">
          <Textarea
            id="assistant-prompt"
            label="Seu pedido"
            value={text}
            maxLength={4000}
            autosize
            minRows={2}
            maxRows={6}
            onChange={(event) => setText(event.currentTarget.value)}
            placeholder="Ex.: adicione leite à lista, registre uma despesa ou consulte as tarefas"
          />
          <Text size="sm" c="dimmed">
            Peça para consultar ou alterar listas, estoque, tarefas e finanças.
            Ações sensíveis pedem confirmação.
          </Text>
          <div className="assistant-options">
            <FileInput
              id="assistant-image"
              label="Foto opcional (máx. 5 MB)"
              placeholder="Escolher foto"
              accept={IMAGE_TYPES.join(",")}
              value={image}
              onChange={pick}
              clearable
              leftSection={<IconPhoto size={16} aria-hidden="true" />}
            />
          </div>
          <Group>
            <Button
              onClick={() => void submit()}
              disabled={!text.trim()}
              loading={busy}
              leftSection={<IconSparkles size={16} aria-hidden="true" />}
            >
              Enviar pedido
            </Button>
          </Group>
        </div>
      )}
      {error && <ErrorNote>{error}</ErrorNote>}
      <AnimatePresence>
        {result && (
          <motion.div
            role="status"
            className="assistant-result"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
          >
            {result.text && <Text>{result.text}</Text>}
            {Boolean(result.applied?.length) && (
              <div className="assistant-applied">
                <Text fw={700} size="sm">
                  Alterações realizadas
                </Text>
                <ul>
                  {result.applied?.map((item, index) => (
                    <li key={`${item.tool}-${index}`}>{item.summary}</li>
                  ))}
                </ul>
              </div>
            )}
            {Boolean(result.issues?.length) && (
              <div className="assistant-issues">
                <Text fw={700} size="sm">
                  Algumas ações não foram concluídas
                </Text>
                <ul>
                  {result.issues?.map((item, index) => (
                    <li key={`${item.tool}-${index}`}>{item.message}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.requires_confirmation &&
              Boolean(result.actions?.length) && (
                <Text fw={700} size="sm" className="assistant-confirm">
                  Confirmação pendente para as ações abaixo.
                </Text>
              )}
            {result.actions?.map((proposal) => (
              <AssistantActionProposal
                key={proposal.proposal_id}
                proposal={proposal}
                busy={actionBusy === proposal.proposal_id}
                onAction={(confirm) =>
                  void respondToProposal(proposal, confirm)
                }
              />
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
