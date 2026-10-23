import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("authenticated account interface", () => {
  it("shows sign-in and registration options when session is absent", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: "Authentication credentials were not provided.",
        }),
        { status: 401 },
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

  it("hides household creation when the user already belongs to a household", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/me"))
        return new Response(
          JSON.stringify({ id: 1, name: "Ana", email: "ana@example.com" }),
        );
      if (String(input).endsWith("/households"))
        return new Response(
          JSON.stringify([{ id: "one", name: "Casa", role: "owner" }]),
        );
      return new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
      });
    });
    render(<App />);
    expect(await screen.findByText("Casa")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Navegação principal" }),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Criar residência")).not.toBeInTheDocument();
    expect(
      screen.getByText(/já participa de uma residência/i),
    ).toBeInTheDocument();
  });

  it("shows household creation when the user has no household", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/me"))
        return new Response(
          JSON.stringify({ id: 1, name: "Ana", email: "ana@example.com" }),
        );
      if (String(input).endsWith("/households"))
        return new Response(JSON.stringify([]));
      return new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
      });
    });
    render(<App />);
    expect(
      await screen.findByLabelText("Criar residência"),
    ).toBeInTheDocument();
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
    const password = screen.getByLabelText(/Senha/);
    fireEvent.change(password, {
      target: { value: "abc12" },
    });
    fireEvent.submit(password.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /pelo menos 6 caracteres/i,
    );
    fireEvent.change(password, {
      target: { value: "abc123!" },
    });
    fireEvent.submit(password.closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /letras e números/i,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("creates a one-time invitation for an owner and displays the token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/me"))
          return new Response(
            JSON.stringify({ id: 1, name: "Ana", email: "ana@example.com" }),
          );
        if (url.endsWith("/households"))
          return new Response(
            JSON.stringify([{ id: "one", name: "Casa", role: "owner" }]),
          );
        if (url.endsWith("/auth/csrf"))
          return new Response(JSON.stringify({ csrfToken: "csrf" }));
        if (
          url.endsWith("/households/one/invitations") &&
          init?.method === "POST"
        )
          return new Response(JSON.stringify({ token: "one-use-token" }));
        return new Response(JSON.stringify({}));
      });
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Criar convite" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/households/one/invitations"),
        expect.any(Object),
      ),
    );
    expect(
      await screen.findByDisplayValue("one-use-token"),
    ).toBeInTheDocument();
  });
});
