import { cleanup, fireEvent, screen } from "@testing-library/react";
import { renderWithProviders as render } from "../../test/render";
import { afterEach, describe, expect, it, vi } from "vitest";
import Shopping from "./Shopping";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Shopping", () => {
  it("shows a loading state while retrieving shared shopping data", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(<Shopping householdId="house-1" role="owner" />);
    expect(screen.getByRole("status")).toHaveTextContent("Carregando");
  });

  it("keeps catalog and inventory visible but hides mutations for viewers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => [] })),
    );
    render(<Shopping householdId="house-1" role="viewer" />);
    expect(
      await screen.findByRole("heading", { name: "Compras e estoque" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Saldo em estoque" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cadastrar produto" }),
    ).not.toBeInTheDocument();
  });

  it("shows an empty-list state and exposes purchased/skipped PATCH actions", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      json: async () =>
        String(input).includes("shopping-lists")
          ? [
              {
                id: 7,
                name: "Feira",
                status: "active",
                items: [
                  {
                    id: 9,
                    product_id: null,
                    name: "Limão",
                    quantity: "2",
                    unit: "un",
                    status: "needed",
                  },
                ],
              },
            ]
          : [],
    }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Shopping householdId="house-1" role="owner" />);
    expect(
      await screen.findByRole("button", { name: "Marcar comprado" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ignorar item" }),
    ).toBeInTheDocument();
  });

  it("shows an API loading error state", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: false,
        json: async () => ({ detail: "Falha de rede" }),
      })),
    );
    render(<Shopping householdId="house-1" role="owner" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Falha de rede");
  });

  it("updates the receipt unit when its selected product changes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () =>
          String(input).includes("/products")
            ? [
                { id: 1, name: "Arroz", unit: "kg", brand: "", category: "" },
                { id: 2, name: "Leite", unit: "L", brand: "", category: "" },
              ]
            : [],
      })),
    );
    render(<Shopping householdId="house-1" role="owner" />);
    const receiptProduct = await screen.findByRole("combobox", {
      name: "Produto",
    });
    fireEvent.change(receiptProduct, { target: { value: "1" } });
    const unit = document.querySelector(
      "input[name='unit-0']",
    ) as HTMLInputElement;
    expect(unit.value).toBe("kg");
    fireEvent.change(receiptProduct, { target: { value: "2" } });
    expect(unit.value).toBe("L");
  });
});
