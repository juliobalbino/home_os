import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, screen } from "@testing-library/react";
import { renderWithProviders as render } from "../../test/render";
import Dashboard from "./Dashboard";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("household dashboard", () => {
  it("announces loading sections and uses a responsive grid", () => {
    vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise(() => {}));
    const { container } = render(
      <Dashboard householdId="home-1" householdName="Casa" />,
    );
    expect(screen.getAllByRole("status")).toHaveLength(3);
    expect(container.querySelector(".dashboard-grid")).toBeInTheDocument();
  });

  it("renders real summary, active shopping items, due chores, and module links", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("financial-summary"))
        return new Response(
          JSON.stringify({ spent_total: 12500, budget_total: 30000 }),
        );
      if (url.endsWith("/settlements"))
        return new Response(
          JSON.stringify([
            { membership_id: 1, name: "Ana", balance_minor: -2500 },
          ]),
        );
      if (url.endsWith("/shopping-lists"))
        return new Response(
          JSON.stringify([
            {
              id: 4,
              name: "Mercado",
              status: "active",
              items: [
                {
                  id: 8,
                  name: "Leite",
                  quantity: "2",
                  unit: "un",
                  status: "needed",
                },
              ],
            },
          ]),
        );
      if (url.endsWith("/chore-occurrences"))
        return new Response(
          JSON.stringify([
            {
              id: 9,
              title: "Lavar louça",
              due_at: "2026-10-22T12:00:00Z",
              status: "pending",
            },
          ]),
        );
      return new Response(JSON.stringify([]));
    });

    render(<Dashboard householdId="home-1" householdName="Casa" />);
    expect(await screen.findByText(/125,00/)).toBeInTheDocument();
    expect(screen.getByText(/175,00/)).toBeInTheDocument();
    expect(screen.getByText(/Leite/)).toBeInTheDocument();
    expect(screen.getByText(/Lavar louça/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Abrir finanças" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Abrir compras e estoque" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Abrir tarefas e rotinas" }),
    ).toBeInTheDocument();
  });

  it("shows per-section errors without hiding available dashboard data", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("financial-summary"))
        return new Response(
          JSON.stringify({ spent_total: 0, budget_total: 0 }),
        );
      if (url.endsWith("/settlements")) return new Response(JSON.stringify([]));
      if (url.endsWith("/shopping-lists"))
        return new Response(JSON.stringify({ detail: "Lista indisponível" }), {
          status: 503,
        });
      if (url.endsWith("/chore-occurrences"))
        return new Response(JSON.stringify([]));
      return new Response(JSON.stringify([]));
    });
    render(<Dashboard householdId="home-1" householdName="Casa" />);
    expect(
      await screen.findByRole("alert", { name: /compras/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/sem gastos registrados/i)).toBeInTheDocument();
  });
});
