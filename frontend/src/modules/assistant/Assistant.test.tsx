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
    expect(
      screen.getByText(/conexão com o chatgpt ainda não foi concluída/i),
    ).toBeInTheDocument();
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
    expect(
      screen.getByText(/conexão com o chatgpt ainda não foi concluída/i),
    ).toBeInTheDocument();
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
        /por enquanto|no momento|ainda não|indisponível/i,
        { selector: "p" },
      );
      const copy = guidance.textContent ?? "";
      expect(copy).toMatch(/por enquanto|no momento|ainda não|indisponível/i);
      expect(copy).toMatch(/administrador|equipe|ajuda|tente novamente/i);
      expect(copy).not.toMatch(
        /ASSISTANT_ENABLED|ASSISTANT_ENCRYPTION_KEY|Fernet|assistant_oauth|OAuth local|configure.*chave|refaça.*oauth/i,
      );
    },
  );
});
