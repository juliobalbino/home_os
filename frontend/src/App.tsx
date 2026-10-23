import { useEffect, useState } from "react";

type Health = { status: string; database: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`${import.meta.env.VITE_API_BASE_URL ?? "/api/v1"}/health`)
      .then((response) => {
        if (!response.ok) throw new Error("Health request failed");
        return response.json() as Promise<Health>;
      })
      .then((result) => active && setHealth(result))
      .catch(() => active && setError(true));
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="shell">
      <div className="eyebrow">HOME OS · BASE DO PROJETO</div>
      <h1>Uma casa, em harmonia.</h1>
      <p className="intro">
        A fundação do seu espaço compartilhado está pronta para começar.
      </p>
      <section className="status" aria-live="polite">
        <span
          className={`indicator ${health ? "healthy" : error ? "failed" : ""}`}
        />
        <div>
          <strong>Conexão com os serviços</strong>
          <p>
            {health
              ? `API disponível · banco ${health.database === "connected" ? "conectado" : health.database}`
              : error
                ? "Não foi possível consultar a API."
                : "Verificando API e banco de dados…"}
          </p>
        </div>
      </section>
    </main>
  );
}
