import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import Finance from "./modules/finance/Finance";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
type User = { id: number; email: string; name: string };
type Household = { id: string; name: string; role: string };

async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${url}`, {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok) {
    const details = Object.values(data).flat().join(" ");
    throw new Error(data.detail ?? details ?? "Falha na solicitação.");
  }
  return data as T;
}

async function csrfHeaders() {
  const result = await request<{ csrfToken: string }>("/auth/csrf");
  return { "X-CSRFToken": result.csrfToken };
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [houses, setHouses] = useState<Household[]>([]);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [inviteToken, setInviteToken] = useState("");
  const [acceptToken, setAcceptToken] = useState("");
  const [financeHousehold, setFinanceHousehold] = useState("");

  async function refresh() {
    try {
      const current = await request<User>("/me");
      setUser(current);
      setHouses(await request<Household[]>("/households"));
    } catch {
      setUser(null);
      setHouses([]);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);

  async function submitAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    const submitted = Object.fromEntries(new FormData(event.currentTarget));
    if (
      mode === "register" &&
      !/^[A-Za-z0-9]{6,}$/.test(String(submitted.password ?? ""))
    ) {
      setMessage(
        "A senha deve ter pelo menos 6 caracteres, usando apenas letras e números.",
      );
      return;
    }
    setBusy(true);
    const values = submitted;
    try {
      const headers = await csrfHeaders();
      if (mode === "register")
        await request("/auth/register", {
          method: "POST",
          headers,
          body: JSON.stringify(values),
        });
      else
        await request("/auth/login", {
          method: "POST",
          headers,
          body: JSON.stringify(values),
        });
      await refresh();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Não foi possível entrar.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function createHouse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const form = event.currentTarget;
    const name = new FormData(form).get("name");
    try {
      const headers = await csrfHeaders();
      await request("/households", {
        method: "POST",
        headers,
        body: JSON.stringify({ name }),
      });
      form.reset();
      await refresh();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Falha ao criar residência.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    const headers = await csrfHeaders();
    await request("/auth/logout", { method: "POST", headers, body: "{}" });
    setUser(null);
    setHouses([]);
  }

  async function issueInvitation(householdId: string) {
    setBusy(true);
    setMessage("");
    try {
      const headers = await csrfHeaders();
      const result = await request<{ token: string }>(
        `/households/${householdId}/invitations`,
        { method: "POST", headers, body: JSON.stringify({ role: "member" }) },
      );
      setInviteToken(result.token);
      setMessage(
        "Convite criado. Compartilhe este token; ele pode ser usado uma única vez.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Falha ao criar convite.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function acceptInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const headers = await csrfHeaders();
      await request(
        `/invitations/${encodeURIComponent(acceptToken.trim())}/accept`,
        { method: "POST", headers, body: "{}" },
      );
      setAcceptToken("");
      setInviteToken("");
      setMessage("Convite aceito.");
      await refresh();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Falha ao aceitar convite.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell app-shell">
      <header className="topbar">
        <div className="eyebrow">HOME OS · ESPAÇO COMPARTILHADO</div>
        {user && (
          <button className="quiet" onClick={() => void logout()}>
            Sair
          </button>
        )}
      </header>
      {!user ? (
        <section className="auth-card">
          <h1>
            {mode === "login"
              ? "Bem-vindo de volta."
              : "Comece pela sua conta."}
          </h1>
          <p className="intro">
            Organize a vida da casa junto com quem mora com você.
          </p>
          <form onSubmit={submitAuth} className="form-stack">
            {mode === "register" && (
              <label>
                Nome
                <input
                  name="name"
                  autoComplete="name"
                  required
                  maxLength={150}
                />
              </label>
            )}
            <label>
              Email
              <input name="email" type="email" autoComplete="email" required />
            </label>
            <label>
              Senha
              <input
                name="password"
                type="password"
                autoComplete={
                  mode === "login" ? "current-password" : "new-password"
                }
                required
                minLength={mode === "register" ? 6 : undefined}
                pattern={mode === "register" ? "[A-Za-z0-9]+" : undefined}
              />
              {mode === "register" && (
                <small>
                  Use pelo menos 6 caracteres, somente letras e números.
                </small>
              )}
            </label>
            <button disabled={busy}>
              {busy ? "Aguarde…" : mode === "login" ? "Entrar" : "Criar conta"}
            </button>
          </form>
          <button
            className="link-button"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setMessage("");
            }}
          >
            {mode === "login" ? "Criar uma conta" : "Já tenho uma conta"}
          </button>
        </section>
      ) : financeHousehold &&
        houses.some((house) => house.id === financeHousehold) ? (
        <section>
          <button className="quiet" onClick={() => setFinanceHousehold("")}>
            Voltar ao início
          </button>
          <Finance
            householdId={financeHousehold}
            role={houses.find((house) => house.id === financeHousehold)!.role}
          />
        </section>
      ) : (
        <section>
          <p className="eyebrow">OLÁ, {user.name.toLocaleUpperCase("pt-BR")}</p>
          <h1>Sua casa, em harmonia.</h1>
          <p className="intro">
            Residências compartilhadas com segurança e simplicidade.
          </p>
          <div className="section-heading">
            <h2>Suas residências</h2>
            <span>{houses.length}</span>
          </div>
          {houses.length ? (
            <div className="house-list">
              {houses.map((house) => (
                <article className="house-card" key={house.id}>
                  <div>
                    <h3>{house.name}</h3>
                    <button onClick={() => setFinanceHousehold(house.id)}>
                      Abrir finanças
                    </button>
                    <p>
                      Seu papel:{" "}
                      {house.role === "owner"
                        ? "responsável"
                        : house.role === "viewer"
                          ? "visualização"
                          : "membro"}
                    </p>
                    {house.role === "owner" && (
                      <button
                        className="quiet"
                        disabled={busy}
                        onClick={() => void issueInvitation(house.id)}
                      >
                        Criar convite
                      </button>
                    )}
                  </div>
                  <span aria-hidden="true">⌂</span>
                </article>
              ))}
            </div>
          ) : (
            <p className="empty">
              Ainda não há residências. Crie a primeira para começar.
            </p>
          )}
          {!houses.length && (
            <form onSubmit={createHouse} className="create-house">
              <label htmlFor="house-name">Criar residência</label>
              <div>
                <input
                  id="house-name"
                  name="name"
                  placeholder="Ex.: Casa da família"
                  maxLength={120}
                  required
                />
                <button disabled={busy}>Criar</button>
              </div>
            </form>
          )}
          {houses.length > 0 && (
            <p className="empty">
              Você já participa de uma residência. Para participar de outra,
              será necessário sair da atual.
            </p>
          )}
          {inviteToken && (
            <div className="invite-token" role="status">
              <label htmlFor="issued-invite-token">
                Token do convite (expira em 7 dias)
              </label>
              <div>
                <input
                  id="issued-invite-token"
                  readOnly
                  value={inviteToken}
                  onFocus={(event) => event.currentTarget.select()}
                />
                <button
                  onClick={() =>
                    void navigator.clipboard.writeText(inviteToken)
                  }
                >
                  Copiar token
                </button>
              </div>
              <small>
                Compartilhe somente com a pessoa convidada; o token pode ser
                usado uma vez.
              </small>
            </div>
          )}
          <form onSubmit={acceptInvitation} className="create-house">
            <label htmlFor="invite-token">Aceitar convite</label>
            <div>
              <input
                id="invite-token"
                value={acceptToken}
                onChange={(event) => setAcceptToken(event.target.value)}
                required
                placeholder="Cole o token recebido"
              />
              <button disabled={busy || !acceptToken.trim()}>Aceitar</button>
            </div>
          </form>
          <nav className="main-nav" aria-label="Navegação principal">
            <span aria-current="page">Início</span>
            <span>Residências</span>
            <span>Membros</span>
          </nav>
        </section>
      )}
      {message && (
        <p role="alert" className="message">
          {message}
        </p>
      )}
    </main>
  );
}
