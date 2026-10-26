import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import Dashboard from "./Dashboard";
import { renderWithProviders as render } from "../../test/render";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("financial-summary"))
      return new Response(JSON.stringify({ spent_total: 0, budget_total: 0 }));
    if (url.endsWith("/auth/csrf"))
      return new Response(JSON.stringify({ csrfToken: "csrf" }));
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
}

describe("dashboard one-tap actions", () => {
  it("lets a member finish a chore and tick a grocery item from the first screen", async () => {
    const fetchMock = mockApi();
    render(
      <Dashboard householdId="home-1" householdName="Casa" role="member" />,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Concluir Lavar louça" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/chore-occurrences/9/complete"),
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() =>
      expect(screen.queryByText("Lavar louça")).not.toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Marcar Leite como comprado" }),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/shopping-items/8"),
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
  });

  it("keeps the dashboard read-only for viewers", async () => {
    mockApi();
    render(
      <Dashboard householdId="home-1" householdName="Casa" role="viewer" />,
    );
    expect(await screen.findByText(/Lavar louça/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Concluir/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /comprado/ }),
    ).not.toBeInTheDocument();
  });
});
