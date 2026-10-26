import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import App from "./App";
import { renderWithProviders as render } from "./test/render";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.location.hash = "";
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
