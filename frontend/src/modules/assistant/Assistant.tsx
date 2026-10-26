import { useEffect, useState } from "react";
import {
  Anchor,
  Badge,
  Button,
  FileInput,
  Group,
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
      return "Assistente desativado. Configure ASSISTANT_ENABLED=true e uma chave Fernet válida em ASSISTANT_ENCRYPTION_KEY.";
    case "missing_or_invalid_encryption_key":
      return "Assistente indisponível: ASSISTANT_ENCRYPTION_KEY precisa ser uma chave Fernet válida.";
    case "credential_unavailable":
      return "As credenciais não podem ser decifradas. Verifique se ASSISTANT_ENCRYPTION_KEY corresponde à chave usada na importação.";
  }
  if (status.status === "consent_required")
    return "O escopo de uso do plano não foi concedido. Refaça o OAuth e autorize o uso.";
  return "Assistente não conectado. Um administrador pode concluir o OAuth local com assistant_oauth.";
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
