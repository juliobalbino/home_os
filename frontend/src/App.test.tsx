import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { renderWithProviders as render } from "./test/render";

afterEach(() => {
  try {
    cleanup();
    vi.restoreAllMocks();
    window.location.hash = "";
  } finally {
    vi.useRealTimers();
  }
});

function signedIn(
  households: unknown[],
  extra?: (url: string, init?: RequestInit) => Response | undefined,
) {
  return vi
    .spyOn(globalThis, "fetch")
    .mockImplementation(async (input, init) => {
      const url = String(input);
      const handled = extra?.(url, init);
      if (handled) return handled;
      if (url.endsWith("/me"))
        return new Response(
          JSON.stringify({ id: 1, name: "Ana", email: "ana@example.com" }),
        );
      if (url.endsWith("/households"))
        return new Response(JSON.stringify(households));
      return new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
      });
    });
}

describe("authenticated account interface", () => {
  it("uses the household timezone for the dashboard date, period, and chore time", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-01T02:30:00.000Z"));
    const fetchMock = signedIn(
      [
        {
          id: "one",
          name: "Casa Azul",
          role: "member",
          timezone: "Asia/Tokyo",
        },
      ],
      (url) => {
        if (url.endsWith("/me") || url.endsWith("/households"))
          return undefined;
        if (url.includes("financial-summary"))
          return new Response(
            JSON.stringify({ spent_total: 0, budget_total: 0 }),
          );
        if (url.endsWith("/settlements"))
          return new Response(JSON.stringify([]));
        if (url.endsWith("/shopping-lists"))
          return new Response(JSON.stringify([]));
        if (url.endsWith("/chore-occurrences"))
          return new Response(
            JSON.stringify([
              {
                id: 1,
                title: "Preparar o café",
                due_at: "2026-10-01T02:00:00Z",
                status: "pending",
              },
            ]),
          );
        return undefined;
      },
    );
    window.location.hash = "#/painel";
    render(<App />);

    expect(
      await screen.findByText("quinta-feira, 1 de outubro"),
    ).toBeInTheDocument();
    expect(await screen.findByText(/11:00/)).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("financial-summary?period=2026-10"),
        expect.anything(),
      ),
    );
  });

  it("uses the household timezone for the finance period and default expense date", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-01T02:30:00.000Z"));
    const fetchMock = signedIn(
      [
        {
          id: "one",
          name: "Casa Azul",
          role: "owner",
          timezone: "Asia/Tokyo",
        },
      ],
      (url) => {
        if (url.endsWith("/me") || url.endsWith("/households"))
          return undefined;
        if (url.includes("financial-summary"))
          return new Response(
            JSON.stringify({ spent_total: 0, budget_total: 0 }),
          );
        if (url.endsWith("/auth/csrf"))
          return new Response(JSON.stringify({ csrfToken: "csrf" }));
        return new Response(JSON.stringify([]));
      },
    );
    window.location.hash = "#/financas";
    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Registrar despesa" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Data")).toHaveValue("2026-10-01");
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("financial-summary?period=2026-10"),
        expect.anything(),
      ),
    );
  });

  it("uses the household timezone for a shopping receipt date", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-01T02:30:00.000Z"));
    const fetchMock = signedIn(
      [
        {
          id: "one",
          name: "Casa Azul",
          role: "owner",
          timezone: "Asia/Tokyo",
        },
      ],
      (url, init) => {
        if (url.endsWith("/me") || url.endsWith("/households"))
          return undefined;
        if (url.endsWith("/auth/csrf"))
          return new Response(JSON.stringify({ csrfToken: "csrf" }));
        if (url.endsWith("/products"))
          return new Response(
            JSON.stringify([
              { id: 1, name: "Arroz", unit: "kg", brand: "", category: "" },
            ]),
          );
        if (url.endsWith("/purchases") && init?.method === "POST")
          return new Response(JSON.stringify({ id: 1 }));
        return new Response(JSON.stringify([]));
      },
    );
    window.location.hash = "#/compras";
    render(<App />);

    fireEvent.change(await screen.findByRole("combobox", { name: "Produto" }), {
      target: { value: "1" },
    });
    fireEvent.change(screen.getByPlaceholderText("0,00"), {
      target: { value: "5,00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Registrar compra" }));
    await waitFor(() => {
      const request = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith("/purchases") && init?.method === "POST",
      );
      expect(request).toBeDefined();
      expect(JSON.parse(String(request?.[1]?.body)).purchased_at).toBe(
        "2026-10-01",
      );
    });
  });

  it("shows sign-in and registration options when session is absent", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Authentication credentials were not provided.",
        }),
        {
          status: 401,
        },
      ),
    );
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "Bem-vindo de volta." }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Criar uma conta" }),
    ).toBeInTheDocument();
  });

  it("opens the household with persistent navigation and no creation form", async () => {
    signedIn([{ id: "one", name: "Casa Azul", role: "owner" }]);
    window.location.hash = "#/casa";
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Principal" });
    expect(nav).toHaveTextContent("Finanças");
    expect(screen.getByRole("link", { name: "Casa" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.queryByLabelText("Criar residência")).not.toBeInTheDocument();
    expect(
      screen.getByText(/já participa de uma residência/i),
    ).toBeInTheDocument();
  });

  it("shows household creation when the user has no household", async () => {
    signedIn([]);
    render(<App />);
    expect(
      await screen.findByLabelText("Criar residência"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Aceitar convite")).toBeInTheDocument();
    expect(
      screen.queryByRole("navigation", { name: "Principal" }),
    ).not.toBeInTheDocument();
  });

  it("validates registration passwords as six or more alphanumeric characters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
      }),
    );
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Criar uma conta" }),
    );
    const password = await screen.findByLabelText(/Senha/);
    fireEvent.change(password, { target: { value: "abc12" } });
    fireEvent.submit(password.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /pelo menos 6 caracteres/i,
    );
    fireEvent.change(password, { target: { value: "abc123!" } });
    fireEvent.submit(password.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /letras e números/i,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("creates a one-time invitation for an owner and displays the token", async () => {
    const fetchMock = signedIn(
      [{ id: "one", name: "Casa", role: "owner" }],
      (url, init) => {
        if (url.endsWith("/auth/csrf"))
          return new Response(JSON.stringify({ csrfToken: "csrf" }));
        if (
          url.endsWith("/households/one/invitations") &&
          init?.method === "POST"
        )
          return new Response(JSON.stringify({ token: "one-use-token" }));
        if (url.endsWith("/members"))
          return new Response(
            JSON.stringify([{ id: 1, name: "Ana", role: "owner" }]),
          );
        return undefined;
      },
    );
    window.location.hash = "#/casa";
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Criar convite" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/households/one/invitations"),
        expect.objectContaining({ body: JSON.stringify({ role: "member" }) }),
      ),
    );
    expect(
      await screen.findByDisplayValue("one-use-token"),
    ).toBeInTheDocument();
  });

  it("switches areas through the hash route", async () => {
    signedIn([{ id: "one", name: "Casa", role: "member" }]);
    render(<App />);
    expect(await screen.findByRole("link", { name: "Painel" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    window.location.hash = "#/tarefas";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(
      await screen.findByRole("heading", { name: "Tarefas e rotinas" }),
    ).toBeInTheDocument();
  });
});
