import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Finance from "./Finance";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Finance", () => {
  it("shows a loading state while fetching household finance", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(<Finance householdId="house-1" role="owner" />);
    expect(screen.getByRole("status")).toHaveTextContent("Carregando finanças");
  });

  it("formats a negative balance smaller than one real with its sign", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: true,
        json: async () =>
          String(url).includes("settlements")
            ? [{ membership_id: 1, name: "Owner", balance_minor: -50 }]
            : String(url).includes("financial-summary")
              ? { spent_total: 0, budget_total: 0 }
              : [],
      })),
    );
    render(<Finance householdId="house-1" role="viewer" />);
    expect(await screen.findByText(/R\$ -0,50/)).toBeInTheDocument();
  });

  it("keeps the finance view read-only for viewers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => [] })),
    );
    render(<Finance householdId="house-1" role="viewer" />);
    await screen.findByRole("heading", { name: "Despesas" });
    expect(
      screen.queryByRole("heading", { name: "Nova categoria" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Despesas" }),
    ).toBeInTheDocument();
  });

  it("retains category input when the create request fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => ({
        ok: !String(url).includes("finance/categories"),
        json: async () =>
          String(url).includes("finance/categories")
            ? { name: ["Falhou"] }
            : [],
      })),
    );
    render(<Finance householdId="house-1" role="owner" />);
    await screen.findByRole("heading", { name: "Nova categoria" });
    const input = screen.getByLabelText("Nome da categoria");
    fireEvent.change(input, { target: { value: "Transporte" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar categoria" }));
    await screen.findByRole("alert");
    expect(input).toHaveValue("Transporte");
  });

  it("accepts decimal percentages and sends them as a string", async () => {
    const fetchMock = vi.fn(async (url: string, options?: RequestInit) => ({
      ok: true,
      json: async () => {
        if (String(url).includes("/members"))
          return [{ id: 1, name: "Owner", role: "owner" }];
        if (String(url).includes("finance/categories"))
          return [{ id: 1, name: "Casa", kind: "general" }];
        if (String(url).includes("financial-summary"))
          return { spent_total: 0, budget_total: 0 };
        if (String(url).includes("settlements")) return [];
        if (String(url).includes("/auth/csrf")) return { csrfToken: "csrf" };
        if (options?.method === "POST") return {};
        return [];
      },
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Finance householdId="house-1" role="owner" />);
    await screen.findByRole("heading", { name: "Registrar despesa" });
    fireEvent.change(screen.getByLabelText("Método de divisão"), {
      target: { value: "percentage" },
    });
    fireEvent.change(screen.getByLabelText("Percentual de Owner"), {
      target: { value: "100,0000" },
    });
    fireEvent.change(screen.getByLabelText("Descrição"), {
      target: { value: "Conta" },
    });
    fireEvent.change(screen.getAllByLabelText("Valor (R$)")[0], {
      target: { value: "10,00" },
    });
    fireEvent.change(screen.getByLabelText("Data"), {
      target: { value: "2026-10-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar despesa" }));
    await screen.findByText("Alterações salvas com sucesso.");
    const body = fetchMock.mock.calls.find(
      ([url, options]) =>
        String(url).includes("/expenses") && options?.method === "POST",
    )?.[1]?.body;
    expect(JSON.parse(String(body)).splits[0].percent).toBe("100.0000");
  });
});
