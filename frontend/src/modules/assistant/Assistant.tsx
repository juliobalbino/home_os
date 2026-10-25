import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
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

export default function Assistant({
  householdId,
  role,
}: {
  householdId: string;
  role: string;
}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"text" | "label">("label");
  const [imageData, setImageData] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void fetch(`${API}/assistant/status`, { credentials: "include" })
      .then((response) => response.json())
      .then(setStatus)
      .catch(() => setStatus({ enabled: false, connected: false }));
  }, []);

  async function submit() {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const csrfResponse = await fetch(`${API}/auth/csrf`, {
        credentials: "include",
      });
      const csrf = (await csrfResponse.json()).csrfToken;
      const response = await fetch(
        `${API}/households/${householdId}/assistant`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({
            text,
            mode,
            ...(imageData ? { image_data: imageData } : {}),
          }),
        },
      );
      const payload = await response.json();
      if (!response.ok)
        throw new Error(
          payload.detail ?? "Não foi possível concluir a análise.",
        );
      setResult(payload);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Assistente indisponível.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="assistant-title" className="assistant-card">
      <h2 id="assistant-title">Assistente da casa</h2>
      <p>
        {status?.connected
          ? "Conectado à sua conta ChatGPT"
          : status?.configuration === "disabled"
            ? "Assistente desativado. Configure ASSISTANT_ENABLED=true e uma chave Fernet válida em ASSISTANT_ENCRYPTION_KEY."
            : status?.configuration === "missing_or_invalid_encryption_key"
              ? "Assistente indisponível: ASSISTANT_ENCRYPTION_KEY precisa ser uma chave Fernet válida."
              : status?.configuration === "credential_unavailable"
                ? "As credenciais não podem ser decifradas. Verifique se ASSISTANT_ENCRYPTION_KEY corresponde à chave usada na importação."
                : status?.status === "consent_required"
                  ? "O escopo de uso do plano não foi concedido. Refaça o OAuth e autorize o uso."
                  : "Assistente não conectado. Um administrador pode concluir o OAuth local com assistant_oauth."}
      </p>
      {status?.connected && (
        <a
          href="https://chatgpt.com/settings/usage"
          target="_blank"
          rel="noreferrer"
        >
          Consultar uso e limites no ChatGPT
        </a>
      )}
      {status?.connected && role !== "viewer" && (
        <>
          <label htmlFor="assistant-prompt">Pergunta</label>
          <label htmlFor="assistant-mode">Tipo de resposta</label>
          <select
            id="assistant-mode"
            value={mode}
            onChange={(event) =>
              setMode(event.target.value as "text" | "label")
            }
          >
            <option value="text">Resposta em texto</option>
            <option value="label">Candidatos de etiqueta</option>
          </select>
          <textarea
            id="assistant-prompt"
            value={text}
            maxLength={4000}
            onChange={(event) => setText(event.target.value)}
            placeholder="Descreva o produto ou peça ajuda"
          />
          <label htmlFor="assistant-image">
            Foto opcional de etiqueta (máx. 5 MiB)
          </label>
          <input
            id="assistant-image"
            type="file"
            accept="image/jpeg,image/png,image/webp"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return setImageData("");
              if (
                file.size > 5 * 1024 * 1024 ||
                !["image/jpeg", "image/png", "image/webp"].includes(file.type)
              ) {
                setError("Use uma imagem JPEG, PNG ou WebP de até 5 MiB.");
                event.target.value = "";
                return;
              }
              const reader = new FileReader();
              reader.onload = () => setImageData(String(reader.result));
              reader.readAsDataURL(file);
            }}
          />
          <button disabled={busy || !text.trim()} onClick={() => void submit()}>
            {busy ? "Analisando…" : "Analisar"}
          </button>
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <div role="status">
          <p>{result.text}</p>
          {result.candidates && (
            <pre>{JSON.stringify(result.candidates, null, 2)}</pre>
          )}
          {result.requires_confirmation ? (
            <strong>
              Confirme antes de salvar. Nenhuma alteração foi feita.
            </strong>
          ) : (
            <small>Nenhuma alteração foi feita.</small>
          )}
        </div>
      )}
    </section>
  );
}
