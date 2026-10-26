import { useState } from "react";
import type { FormEvent } from "react";
import {
  Anchor,
  Button,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { AnimatePresence, motion } from "motion/react";
import { reason, send } from "../lib/api";
import { TileMark, TileRun } from "../ui/Tile";
import { ErrorNote } from "../ui/parts";

export function AuthScreen({
  onSignedIn,
}: {
  onSignedIn: () => Promise<void>;
}) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const register = mode === "register";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (register && !/^[A-Za-z0-9]{6,}$/.test(String(values.password ?? ""))) {
      setMessage(
        "A senha deve ter pelo menos 6 caracteres, usando apenas letras e números.",
      );
      return;
    }
    setBusy(true);
    try {
      await send(register ? "/auth/register" : "/auth/login", values);
      await onSignedIn();
    } catch (error) {
      setMessage(reason(error, "Não foi possível entrar."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth">
      <div className="auth-wall">
        <TileRun
          motifs={["arcos", "flor"]}
          size={64}
          className="auth-wall-tiles"
        />
        <div className="auth-brand">
          <TileMark motif="estrela" size={44} />
          <span>Home OS</span>
        </div>
      </div>
      <section className="auth-panel" aria-labelledby="auth-title">
        <div>
          <motion.div
            key={mode}
            initial={{ opacity: 1, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2, ease: [0.2, 0.9, 0.3, 1] }}
          >
            <Title order={1} id="auth-title" className="auth-title">
              {register ? "Comece pela sua conta." : "Bem-vindo de volta."}
            </Title>
          </motion.div>
          <Text c="dimmed" mt={8} mb={28}>
            Organize a vida da casa junto com quem mora com você.
          </Text>
          <form onSubmit={submit}>
            <Stack gap="md">
              <AnimatePresence initial={false}>
                {register && (
                  <motion.div
                    key="name"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2, ease: [0.2, 0.9, 0.3, 1] }}
                    style={{ overflow: "hidden" }}
                  >
                    <TextInput
                      label="Nome"
                      name="name"
                      autoComplete="name"
                      required
                      maxLength={150}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
              <TextInput
                label="Email"
                name="email"
                type="email"
                autoComplete="email"
                required
              />
              <PasswordInput
                label="Senha"
                name="password"
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={register ? 6 : undefined}
                pattern={register ? "[A-Za-z0-9]+" : undefined}
                description={
                  register
                    ? "Use pelo menos 6 caracteres, somente letras e números."
                    : undefined
                }
                visibilityToggleButtonProps={{
                  "aria-label": "Mostrar ou ocultar senha",
                }}
              />
              {message && <ErrorNote>{message}</ErrorNote>}
              <Button type="submit" loading={busy} fullWidth mt={4}>
                {register ? "Criar conta" : "Entrar"}
              </Button>
            </Stack>
          </form>
        </div>
        <Text size="sm" c="dimmed" mt={24}>
          {register ? "Já usa o Home OS? " : "Primeira vez por aqui? "}
          <Anchor
            component="button"
            type="button"
            fw={600}
            onClick={() => {
              setMode(register ? "login" : "register");
              setMessage("");
            }}
          >
            {register ? "Já tenho uma conta" : "Criar uma conta"}
          </Anchor>
        </Text>
      </section>
    </main>
  );
}
