import { useEffect, useState } from "react";
import {
  Avatar,
  Badge,
  Button,
  CopyButton,
  Group,
  SegmentedControl,
  Text,
  TextInput,
  useMantineColorScheme,
} from "@mantine/core";
import type { MantineColorScheme } from "@mantine/core";
import { IconCheck, IconCopy, IconLogout } from "@tabler/icons-react";
import { list, reason, request, roleLabel, send } from "../lib/api";
import type { Household, Member, User } from "../lib/api";
import {
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  TileSection,
} from "../ui/parts";

export function HouseholdPage({
  household,
  user,
  onSignOut,
}: {
  household: Household;
  user: User;
  onSignOut: () => void;
}) {
  const owner = household.role === "owner";
  const [members, setMembers] = useState<Member[] | null>(null);
  const [membersError, setMembersError] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { colorScheme, setColorScheme } = useMantineColorScheme();

  useEffect(() => {
    let active = true;
    request<Member[]>(`/households/${household.id}/members`)
      .then((rows) => active && setMembers(list<Member>(rows)))
      .catch((cause: unknown) => {
        if (!active) return;
        setMembers([]);
        setMembersError(
          reason(cause, "Não foi possível carregar os moradores."),
        );
      });
    return () => {
      active = false;
    };
  }, [household.id]);

  async function invite() {
    setBusy(true);
    setError("");
    try {
      const result = await send<{ token: string }>(
        `/households/${household.id}/invitations`,
        {
          role: inviteRole,
        },
      );
      setToken(result.token);
    } catch (cause) {
      setError(reason(cause, "Falha ao criar convite."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <PageHeader motif="estrela" title={household.name}>
        Seu papel: {roleLabel(household.role).toLowerCase()}
      </PageHeader>
      <div className="tile-wall casa-wall">
        <TileSection title="Quem mora aqui" id="moradores">
          {members === null ? (
            <Loading label="Carregando moradores…" lines={2} />
          ) : membersError ? (
            <ErrorNote>{membersError}</ErrorNote>
          ) : members.length ? (
            <ul className="rows">
              {members.map((member) => (
                <li key={member.id} className="row">
                  <Avatar color="azulejo" radius="sm" name={member.name} />
                  <span className="row-main">
                    <span className="row-title">{member.name}</span>
                  </span>
                  <Badge
                    variant="light"
                    color={member.role === "owner" ? "azulejo" : "gray"}
                  >
                    {roleLabel(member.role)}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>Nenhum morador encontrado.</EmptyState>
          )}
        </TileSection>

        <TileSection title="Convidar alguém" id="convite">
          {owner ? (
            <div className="stack">
              <Text size="sm" c="dimmed">
                Gere um código de convite e envie para a pessoa. Ele vale por 7
                dias e pode ser usado uma única vez.
              </Text>
              <SegmentedControl
                value={inviteRole}
                onChange={setInviteRole}
                aria-label="Papel da pessoa convidada"
                data={[
                  { value: "member", label: "Membro" },
                  { value: "viewer", label: "Só visualiza" },
                ]}
              />
              <Group>
                <Button onClick={() => void invite()} loading={busy}>
                  Criar convite
                </Button>
              </Group>
              {error && <ErrorNote>{error}</ErrorNote>}
              {token && (
                <div className="token" role="status">
                  <Text size="sm" fw={600}>
                    Convite criado. Compartilhe este código; ele pode ser usado
                    uma única vez.
                  </Text>
                  <Group gap="xs" wrap="nowrap" align="flex-end">
                    <TextInput
                      id="issued-invite-token"
                      label="Código do convite (expira em 7 dias)"
                      readOnly
                      value={token}
                      onFocus={(event) => event.currentTarget.select()}
                      className="token-input"
                    />
                    <CopyButton value={token}>
                      {({ copied, copy }) => (
                        <Button
                          variant={copied ? "filled" : "light"}
                          onClick={copy}
                          leftSection={
                            copied ? (
                              <IconCheck size={16} />
                            ) : (
                              <IconCopy size={16} />
                            )
                          }
                        >
                          {copied ? "Copiado" : "Copiar código"}
                        </Button>
                      )}
                    </CopyButton>
                  </Group>
                </div>
              )}
            </div>
          ) : (
            <Text size="sm" c="dimmed">
              Somente a pessoa responsável pela casa pode criar convites.
            </Text>
          )}
        </TileSection>

        <TileSection title="Sua conta" id="conta">
          <div className="stack">
            <div>
              <Text fw={600}>{user.name}</Text>
              <Text size="sm" c="dimmed">
                {user.email}
              </Text>
            </div>
            <Text size="sm" c="dimmed">
              Você já participa de uma residência. Para participar de outra,
              será necessário sair da atual.
            </Text>
            <div>
              <Text size="sm" fw={600} mb={6} id="scheme-label">
                Aparência
              </Text>
              <SegmentedControl
                aria-labelledby="scheme-label"
                value={colorScheme}
                onChange={(value) =>
                  setColorScheme(value as MantineColorScheme)
                }
                data={[
                  { value: "auto", label: "Automática" },
                  { value: "light", label: "Clara" },
                  { value: "dark", label: "Escura" },
                ]}
              />
            </div>
            <Group>
              <Button
                variant="default"
                leftSection={<IconLogout size={16} />}
                onClick={onSignOut}
              >
                Sair
              </Button>
            </Group>
          </div>
        </TileSection>
      </div>
    </div>
  );
}
