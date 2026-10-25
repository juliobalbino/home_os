import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Assistant from "./Assistant";

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
      expect(screen.getByText(/não conectado/i)).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: /analisar/i }),
      ).not.toBeInTheDocument();
    });
  });
});
