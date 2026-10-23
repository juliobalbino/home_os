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

  it("shows household navigation and create form for an authenticated user", async () => {
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
    expect(screen.getByLabelText("Criar residência")).toBeInTheDocument();
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
