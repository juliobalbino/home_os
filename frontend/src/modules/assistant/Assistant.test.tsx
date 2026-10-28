import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Assistant from "./Assistant";
import { renderWithProviders as render } from "../../test/render";

describe("Assistant", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => cleanup());

  it("reports disconnected state and lets household members submit an explicit candidate request", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input) => {
        const url = String(input);
        return new Response(
          JSON.stringify(
            url.endsWith("/assistant/status")
              ? { enabled: true, connected: true, status: "connected" }
              : {
                  text: "Milk candidate",
                  candidates: { name: "Milk" },
                  requires_confirmation: true,
                },
          ),
          { status: 200 },
        );
      });
    render(<Assistant householdId="h-1" role="member" />);
    expect(await screen.findByText(/conectado/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/pergunta/i), {
      target: { value: "O que está nesta etiqueta?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /analisar/i }));
    expect(
      await screen.findByText(/confirme antes de salvar/i),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/households/h-1/assistant"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("does not show a request action to viewers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ enabled: false, connected: false }), {
        status: 200,
      }),
    );
    render(<Assistant householdId="h-1" role="viewer" />);
    await waitFor(() => {
      expect(
        screen.getByText(/a conexão com o ChatGPT ainda não foi concluída/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /analisar/i }),
      ).not.toBeInTheDocument();
    });
  });

  it("starts an approved pairing with CSRF and shows one-time helper instructions", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status"))
          return new Response(
            JSON.stringify({ enabled: true, connected: false }),
            { status: 200 },
          );
        if (url.endsWith("/auth/csrf"))
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        if (url.endsWith("/assistant/connect/pairings") && method === "POST")
          return new Response(
            JSON.stringify({
              pairing_id: "pairing-fake-001",
              pairing_code: "FAKE-4821",
            }),
            { status: 201 },
          );
        if (url.endsWith("/assistant/connect/pairings/pairing-fake-001"))
          return new Response(JSON.stringify({ status: "pending" }), {
            status: 200,
          });
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="member" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Conectar ChatGPT" }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("FAKE-4821");
    expect(dialog).toHaveTextContent(/windows/i);
    expect(dialog).toHaveTextContent(/auxiliar|assistente/i);
    expect(
      screen.getByRole("link", { name: /baixar|download/i }),
    ).toHaveAttribute("href", "/api/v1/assistant/connect/helper");

    const pairingPost = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/assistant/connect/pairings") &&
        init?.method === "POST",
    );
    expect(pairingPost).toBeDefined();
    expect(pairingPost?.[1]?.headers).toMatchObject({
      "X-CSRFToken": "fake-csrf-token",
    });
    const body = JSON.parse(String(pairingPost?.[1]?.body));
    expect(JSON.stringify(body)).not.toMatch(
      /credential|password|access.?token|refresh.?token/i,
    );
    expect(JSON.stringify(body)).not.toContain("FAKE-4821");
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(
      /oauth|client_secret/i,
    );
  });

  it("allows a viewer to initiate their own pairing without showing Analisar", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/assistant/status"))
        return new Response(
          JSON.stringify({ enabled: true, connected: false }),
          { status: 200 },
        );
      if (url.endsWith("/auth/csrf"))
        return new Response(JSON.stringify({ csrfToken: "fake-csrf-token" }), {
          status: 200,
        });
      if (url.endsWith("/assistant/connect/pairings") && method === "POST")
        return new Response(
          JSON.stringify({
            pairing_id: "pairing-viewer-fake",
            pairing_code: "VIEW-1937",
          }),
          { status: 201 },
        );
      if (url.endsWith("/assistant/connect/pairings/pairing-viewer-fake"))
        return new Response(JSON.stringify({ status: "pending" }), {
          status: 200,
        });
      throw new Error(`Unexpected fetch: ${method} ${url}`);
    });
    render(<Assistant householdId="h-1" role="viewer" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Conectar ChatGPT" }),
    );
    expect(await screen.findByRole("dialog")).toHaveTextContent("VIEW-1937");
    expect(
      screen.queryByRole("button", { name: /analisar/i }),
    ).not.toBeInTheDocument();
  });

  it("refreshes status and closes pairing modal when polling reports completion", async () => {
    let statusRequests = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status")) {
          statusRequests += 1;
          return new Response(
            JSON.stringify(
              statusRequests === 1
                ? { enabled: true, connected: false }
                : { enabled: true, connected: true, status: "connected" },
            ),
            { status: 200 },
          );
        }
        if (url.endsWith("/auth/csrf"))
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        if (url.endsWith("/assistant/connect/pairings") && method === "POST")
          return new Response(
            JSON.stringify({
              pairing_id: "pairing-complete-fake",
              pairing_code: "DONE-7350",
            }),
            { status: 201 },
          );
        if (url.endsWith("/assistant/connect/pairings/pairing-complete-fake"))
          return new Response(JSON.stringify({ status: "completed" }), {
            status: 200,
          });
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="member" />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Conectar ChatGPT" }),
    );
    await waitFor(
      () => {
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
        expect(
          screen.getByText(/conectado à sua conta chatgpt/i),
        ).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
    expect(statusRequests).toBeGreaterThan(1);
    expect(
      fetchMock.mock.calls.some(([input]) => String(input).includes("oauth")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).includes("/assistant/connect/helper"),
      ),
    ).toBe(false);
  });

  it("lets a viewer cancel the disconnect confirmation without disconnecting", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status")) {
          return new Response(
            JSON.stringify({
              enabled: true,
              connected: true,
              can_disconnect: true,
              status: "connected",
            }),
            { status: 200 },
          );
        }
        if (url.endsWith("/auth/csrf") && method === "GET") {
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        }
        if (url.endsWith("/assistant/disconnect") && method === "POST") {
          return new Response(
            JSON.stringify({ disconnected: true, revocation_confirmed: true }),
            { status: 200 },
          );
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="viewer" />);

    const disconnect = await screen.findByRole("button", {
      name: "Desconectar ChatGPT",
    });
    expect(disconnect).toBeInTheDocument();
    fireEvent.click(disconnect);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(/home os/i);
    expect(dialog).toHaveTextContent(
      /continuará conectado às sessões do site do chatgpt e em outros dispositivos/i,
    );
    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input).endsWith("/assistant/disconnect") &&
          init?.method === "POST",
      ),
    ).toHaveLength(0);
  });

  it("confirms disconnect, refreshes status, and reports Portuguese success", async () => {
    let disconnected = false;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status")) {
          return new Response(
            JSON.stringify({
              enabled: true,
              connected: !disconnected,
              can_disconnect: !disconnected,
              status: disconnected ? "disconnected" : "connected",
            }),
            { status: 200 },
          );
        }
        if (url.endsWith("/auth/csrf") && method === "GET") {
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        }
        if (url.endsWith("/assistant/disconnect") && method === "POST") {
          disconnected = true;
          return new Response(
            JSON.stringify({ disconnected: true, revocation_confirmed: true }),
            { status: 200 },
          );
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="member" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Desconectar ChatGPT" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirmar desconexão" }),
    );

    expect(
      await screen.findByText(/desconectado com sucesso/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/conecte sua conta chatgpt/i)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input).endsWith("/assistant/disconnect") &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("keeps the disconnect success message when the status refresh fails", async () => {
    let statusRequests = 0;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status")) {
          statusRequests += 1;
          if (statusRequests > 1) return new Response("", { status: 500 });
          return new Response(
            JSON.stringify({
              enabled: true,
              connected: true,
              can_disconnect: true,
              status: "connected",
            }),
            { status: 200 },
          );
        }
        if (url.endsWith("/auth/csrf") && method === "GET") {
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        }
        if (url.endsWith("/assistant/disconnect") && method === "POST") {
          return new Response(
            JSON.stringify({ disconnected: true, revocation_confirmed: true }),
            { status: 200 },
          );
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="member" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Desconectar ChatGPT" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirmar desconexão" }),
    );

    expect(
      await screen.findByText(/desconectado com sucesso/i),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      screen.queryByText(/não foi possível desconectar|falha ao desconectar/i),
    ).not.toBeInTheDocument();
    expect(statusRequests).toBe(2);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/assistant/disconnect"),
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("warns when local credentials are removed but remote revocation is unconfirmed", async () => {
    let disconnected = false;
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.endsWith("/assistant/status")) {
          return new Response(
            JSON.stringify({
              enabled: true,
              connected: !disconnected,
              can_disconnect: !disconnected,
              status: disconnected ? "disconnected" : "connected",
            }),
            { status: 200 },
          );
        }
        if (url.endsWith("/auth/csrf") && method === "GET") {
          return new Response(
            JSON.stringify({ csrfToken: "fake-csrf-token" }),
            { status: 200 },
          );
        }
        if (url.endsWith("/assistant/disconnect") && method === "POST") {
          disconnected = true;
          return new Response(
            JSON.stringify({ disconnected: true, revocation_confirmed: false }),
            { status: 200 },
          );
        }
        throw new Error(`Unexpected fetch: ${method} ${url}`);
      });
    render(<Assistant householdId="h-1" role="member" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Desconectar ChatGPT" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Confirmar desconexão" }),
    );

    expect(
      await screen.findByText(
        /credenciais.*home os.*removidas.*revogação remota.*não.*confirmada/i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/conecte sua conta chatgpt/i)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input).endsWith("/assistant/disconnect") &&
          init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it.each([
    [
      "configuração desativada",
      { enabled: false, connected: false, configuration: "disabled" },
    ],
    [
      "chave de criptografia ausente ou inválida",
      {
        enabled: false,
        connected: false,
        configuration: "missing_or_invalid_encryption_key",
      },
    ],
    [
      "credencial indisponível",
      {
        enabled: false,
        connected: false,
        configuration: "credential_unavailable",
      },
    ],
    [
      "consentimento necessário",
      { enabled: true, connected: false, status: "consent_required" },
    ],
    ["fallback desconectado", { enabled: true, connected: false }],
  ])(
    "gives warm, useful pt-BR guidance for %s without exposing setup details",
    async (_label, status) => {
      vi.spyOn(globalThis, "fetch").mockResolvedValue(
        new Response(JSON.stringify(status), { status: 200 }),
      );
      render(<Assistant householdId="h-1" role="member" />);

      const guidance = await screen.findByText(
        /por enquanto|no momento|ainda não|indisponível|conecte/i,
        { selector: "p" },
      );
      const copy = guidance.textContent ?? "";
      expect(copy).toMatch(
        /por enquanto|no momento|ainda não|indisponível|conecte/i,
      );
      expect(copy).toMatch(
        /conecte|administrador|equipe|ajuda|tente novamente/i,
      );
      expect(copy).not.toMatch(
        /ASSISTANT_ENABLED|ASSISTANT_ENCRYPTION_KEY|Fernet|assistant_oauth|OAuth local|configure.*chave|refaça.*oauth/i,
      );
    },
  );
});
