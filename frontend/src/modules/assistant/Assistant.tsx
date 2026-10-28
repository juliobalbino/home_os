import { useEffect, useState } from "react";
import {
  Anchor,
  Badge,
  Button,
  FileInput,
  Group,
  Modal,
  NativeSelect,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { IconExternalLink, IconPhoto, IconSparkles } from "@tabler/icons-react";
import { AnimatePresence, motion } from "motion/react";
import { reason, request, send } from "../../lib/api";
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
  candidates: Record<string, unknown> | null;
  requires_confirmation: boolean;
};

const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];

function statusText(status: Status | null) {
  if (!status) return "Verificando o assistente…";
  if (status.connected) return "Conectado à sua conta ChatGPT";
  switch (status.configuration) {
    case "disabled":
      return "O Assistente está desativado no momento. Peça ajuda à pessoa administradora da casa para ativá-lo.";
    case "missing_or_invalid_encryption_key":
      return "O Assistente está indisponível no momento. Peça ajuda à pessoa administradora da casa.";
    case "credential_unavailable":
      return "O Assistente está indisponível no momento. Peça ajuda à pessoa administradora da casa.";
  }
  if (status.status === "consent_required")
    return "A conexão do Assistente está indisponível até ser autorizada novamente. Peça à pessoa administradora da casa para reconectar.";
  return "A conexão com o ChatGPT ainda não foi concluída. Peça ajuda à pessoa administradora da casa.";
}

function show(value: unknown) {
  return typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
    ? String(value)
    : JSON.stringify(value);
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
  const [mode, setMode] = useState<"text" | "label">("label");
  const [image, setImage] = useState<File | null>(null);
  const [imageData, setImageData] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnectBusy, setDisconnectBusy] = useState(false);
  const [disconnectError, setDisconnectError] = useState("");
  const [disconnectMessage, setDisconnectMessage] = useState("");

  useEffect(() => {
    request<Status>("/assistant/status")
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, connected: false }));
  }, []);

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
          mode,
          ...(imageData ? { image_data: imageData } : {}),
        }),
      );
    } catch (cause) {
      setError(reason(cause, "Não foi possível concluir a análise."));
    } finally {
      setBusy(false);
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
          Remover o acesso do Home OS? Isso remove o acesso do Home OS à sua
          conta. Você continuará conectado às sessões do site do ChatGPT e em
          outros dispositivos. Para conectar outra conta, será necessário seguir
          o processo atual de conexão.
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
            label="Pergunta"
            value={text}
            maxLength={4000}
            autosize
            minRows={2}
            maxRows={6}
            onChange={(event) => setText(event.currentTarget.value)}
            placeholder="Descreva o produto ou peça ajuda"
          />
          <div className="assistant-options">
            <NativeSelect
              id="assistant-mode"
              label="Tipo de resposta"
              value={mode}
              onChange={(event) =>
                setMode(event.currentTarget.value as "text" | "label")
              }
              data={[
                { value: "label", label: "Candidatos de etiqueta" },
                { value: "text", label: "Resposta em texto" },
              ]}
            />
            <FileInput
              id="assistant-image"
              label="Foto opcional de etiqueta (máx. 5 MB)"
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
              Analisar
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
            <Text>{result.text}</Text>
            {result.candidates && (
              <dl className="candidates">
                {Object.entries(result.candidates).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{show(value)}</dd>
                  </div>
                ))}
              </dl>
            )}
            {result.requires_confirmation ? (
              <Text fw={700} size="sm" className="assistant-confirm">
                Confirme antes de salvar. Nenhuma alteração foi feita.
              </Text>
            ) : (
              <Text size="sm" c="dimmed">
                Nenhuma alteração foi feita.
              </Text>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}
