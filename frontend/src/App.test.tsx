import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import App from "./App";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("App health status", () => {
  it("consulta o endpoint e informa que o banco está conectado", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", database: "connected" }), {
        status: 200,
      }),
    );
    render(<App />);
    expect(
      await screen.findByText("API disponível · banco conectado"),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/health");
  });

  it("exibe mensagem quando a API não responde", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("offline"));
    render(<App />);
    expect(
      await screen.findByText("Não foi possível consultar a API."),
    ).toBeInTheDocument();
  });
});
