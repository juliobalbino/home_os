import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Chores from "./Chores";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Chores", () => {
  it("shows loading and read-only viewer UI", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(<Chores householdId="home-1" role="viewer" />);
    expect(screen.getByRole("status")).toHaveTextContent("Carregando");
    expect(
      await screen.findByRole("heading", { name: "Tarefas e rotinas" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Criar tarefa" }),
    ).not.toBeInTheDocument();
  });

  it("creates and completes a chore occurrence", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, options?: RequestInit) => ({
        ok: true,
        json: async () =>
          String(input).includes("chore-occurrences")
            ? [
                {
                  id: 3,
                  title: "Regar",
                  due_at: "2026-03-08T13:00:00Z",
                  status: "pending",
                },
              ]
            : options?.method === "POST"
              ? { id: 8, title: "Regar" }
              : [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<Chores householdId="home-1" role="owner" />);
    fireEvent.change(await screen.findByLabelText("Título"), {
      target: { value: "Regar" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Criar tarefa" }));
    expect(
      await screen.findByText("Tarefa criada com sucesso."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Concluir" }));
    expect(
      await screen.findByText("Ocorrência concluída."),
    ).toBeInTheDocument();
  });
});
