import { useState } from "react";
import type { FormEvent } from "react";
import { Button, Group, Text, TextInput, Title } from "@mantine/core";
import { IconDoorEnter, IconHomePlus } from "@tabler/icons-react";
import { reason, send } from "../lib/api";
import type { User } from "../lib/api";
import { TileMark, TileRun } from "../ui/Tile";
import { ErrorNote } from "../ui/parts";

/** First run: no household yet. Create one or join with an invitation. */
export function Onboarding({
  user,
  onJoined,
  onSignOut,
}: {
  user: User;
  onJoined: () => Promise<void>;
  onSignOut: () => void;
}) {
  const [busy, setBusy] = useState<"" | "create" | "accept">("");
  const [error, setError] = useState("");
  const [token, setToken] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setBusy("create");
    setError("");
    try {
      await send("/households", { name: new FormData(form).get("name") });
      form.reset();
      await onJoined();
    } catch (cause) {
      setError(reason(cause, "Falha ao criar residência."));
    } finally {
      setBusy("");
    }
  }

  async function accept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("accept");
    setError("");
    try {
      await send(`/invitations/${encodeURIComponent(token.trim())}/accept`, {});
      setToken("");
      await onJoined();
    } catch (cause) {
      setError(reason(cause, "Falha ao aceitar convite."));
    } finally {
      setBusy("");
    }
  }

  return (
    <main className="onboarding">
      <header className="onboarding-top">
        <div className="brand">
          <TileMark motif="estrela" size={32} />
          <span>Home OS</span>
        </div>
        <Button variant="subtle" color="gray" onClick={onSignOut}>
          Sair
        </Button>
      </header>
      <div className="onboarding-body">
        <Title order={1}>
          Olá, {user.name.split(" ")[0]}. Qual é a sua casa?
        </Title>
        <Text c="dimmed" mt={8} maw={520}>
          Ainda não há residências. Crie a primeira para começar, ou entre na
          casa de alguém com o token de convite que você recebeu.
        </Text>
        {error && (
          <div className="onboarding-error">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
        <div className="tile-wall onboarding-wall">
          <form className="tile onboarding-tile" onSubmit={create}>
            <TileRun motifs={["estrela"]} size={14} className="barrado" />
            <IconHomePlus
              size={28}
              stroke={1.6}
              className="onboarding-icon"
              aria-hidden="true"
            />
            <Title order={2}>Começar uma casa nova</Title>
            <Text size="sm" c="dimmed">
              Você será a pessoa responsável e poderá convidar quem mora com
              você.
            </Text>
            <TextInput
              id="house-name"
              name="name"
              label="Criar residência"
              placeholder="Ex.: Casa da família"
              maxLength={120}
              required
            />
            <Button
              type="submit"
              loading={busy === "create"}
              disabled={busy === "accept"}
            >
              Criar
            </Button>
          </form>
          <form className="tile onboarding-tile" onSubmit={accept}>
            <TileRun motifs={["arcos"]} size={14} className="barrado" />
            <IconDoorEnter
              size={28}
              stroke={1.6}
              className="onboarding-icon"
              aria-hidden="true"
            />
            <Title order={2}>Entrar com convite</Title>
            <Text size="sm" c="dimmed">
              O token vale por 7 dias e só pode ser usado uma vez.
            </Text>
            <TextInput
              id="invite-token"
              label="Aceitar convite"
              placeholder="Cole o token recebido"
              value={token}
              onChange={(event) => setToken(event.currentTarget.value)}
              required
            />
            <Group>
              <Button
                type="submit"
                variant="light"
                loading={busy === "accept"}
                disabled={!token.trim() || busy === "create"}
              >
                Aceitar
              </Button>
            </Group>
          </form>
        </div>
      </div>
    </main>
  );
}
