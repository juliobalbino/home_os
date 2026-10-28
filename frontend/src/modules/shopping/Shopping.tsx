import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ActionIcon,
  Badge,
  Button,
  NativeSelect,
  Text,
  TextInput,
} from "@mantine/core";
import { IconPlus, IconReceipt, IconTrash } from "@tabler/icons-react";
import { list, reason, request, send } from "../../lib/api";
import {
  currencyToMinor,
  DEFAULT_TIME_ZONE,
  localDay,
  money,
  quantity,
} from "../../lib/format";
import { useToast } from "../../ui/Toaster";
import { SectionNav } from "../../ui/SectionNav";
import {
  EmptyState,
  ErrorNote,
  FlipTile,
  Loading,
  PageHeader,
  TileSection,
} from "../../ui/parts";

type Product = {
  id: number;
  name: string;
  unit: string;
  brand: string;
  category: string;
};
type Item = {
  id: number;
  product_id: number | null;
  name: string;
  quantity: string;
  unit: string;
  status: string;
};
type ShoppingList = { id: number; name: string; status: string; items: Item[] };
type Stock = {
  product_id: number;
  name: string;
  quantity: string;
  unit: string;
};
type ReceiptRow = { product_id: string; quantity: string; price: string };

const blankRow = (): ReceiptRow => ({
  product_id: "",
  quantity: "1",
  price: "",
});
const ITEM_STATUS: Record<string, string> = {
  needed: "Falta comprar",
  purchased: "Comprado",
  skipped: "Ignorado",
};
const LIST_STATUS: Record<string, string> = {
  active: "ativa",
  archived: "arquivada",
  completed: "concluída",
};

function receiptTotal(rows: ReceiptRow[]) {
  let total = 0;
  for (const row of rows) {
    const amount = Number(row.quantity.replace(",", "."));
    try {
      if (!Number.isFinite(amount) || amount <= 0) return null;
      total += Math.round(amount * currencyToMinor(row.price));
    } catch {
      return null;
    }
  }
  return total;
}

export default function Shopping({
  householdId,
  role,
  timezone = DEFAULT_TIME_ZONE,
}: {
  householdId: string;
  role: string;
  timezone?: string;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [lists, setLists] = useState<ShoppingList[]>([]);
  const [stock, setStock] = useState<Stock[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rows, setRows] = useState<ReceiptRow[]>([blankRow()]);
  const readOnly = role === "viewer";
  const pendingPurchase = useRef<{ payload: string; key: string } | null>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [productRows, listRows, stockRows] = await Promise.all([
        request<Product[]>(`/households/${householdId}/products`),
        request<ShoppingList[]>(`/households/${householdId}/shopping-lists`),
        request<Stock[]>(`/households/${householdId}/inventory`),
      ]);
      const nextLists = list<ShoppingList>(listRows);
      setProducts(list<Product>(productRows));
      setLists(nextLists);
      setStock(list<Stock>(stockRows));
      setSelected((current) =>
        current && nextLists.some((entry) => String(entry.id) === current)
          ? current
          : nextLists[0]
            ? String(nextLists[0].id)
            : "",
      );
    } catch (cause) {
      setError(reason(cause, "Não foi possível carregar os dados."));
    } finally {
      setLoading(false);
    }
  }, [householdId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function submit(
    event: FormEvent<HTMLFormElement>,
    path: string,
    build: (data: FormData) => unknown,
    success: string,
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    setError("");
    try {
      await send(path, build(new FormData(form)));
      form.reset();
      toast.success(success);
      await refresh();
    } catch (cause) {
      setError(reason(cause, "Falha ao salvar."));
    }
  }

  async function updateListItem(itemId: number, status: string) {
    setError("");
    setLists((current) =>
      current.map((entry) => ({
        ...entry,
        items: entry.items.map((item) =>
          item.id === itemId ? { ...item, status } : item,
        ),
      })),
    );
    try {
      await send(`/shopping-items/${itemId}`, { status }, "PATCH");
      toast.success(
        status === "purchased"
          ? "Item marcado como comprado."
          : "Item ignorado.",
      );
    } catch (cause) {
      setError(reason(cause, "Falha ao atualizar o item."));
    }
    await refresh();
  }

  async function confirmPurchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setError("");
    let encoded: string;
    try {
      encoded = JSON.stringify({
        purchased_at: localDay(new Date(), timezone),
        store_name: data.get("store_name"),
        items: rows.map((row, index) => ({
          product_id: Number(row.product_id),
          quantity: row.quantity,
          unit: String(data.get(`unit-${index}`)),
          unit_price_minor: currencyToMinor(row.price),
        })),
      });
    } catch (cause) {
      setError(reason(cause, "Confira os preços informados."));
      return;
    }
    // Retries of the same receipt reuse the key so the server records it once.
    if (pendingPurchase.current?.payload !== encoded)
      pendingPurchase.current = { payload: encoded, key: crypto.randomUUID() };
    setBusy(true);
    try {
      const response = await send<{ id: number }>(
        `/households/${householdId}/purchases`,
        encoded,
        "POST",
        { "Idempotency-Key": pendingPurchase.current.key },
      );
      form.reset();
      pendingPurchase.current = null;
      setRows([blankRow()]);
      toast.success(
        `Compra ${response.id} registrada; estoque e financeiro atualizados.`,
      );
      await refresh();
    } catch (cause) {
      setError(reason(cause, "Falha ao confirmar a compra."));
    } finally {
      setBusy(false);
    }
  }

  const setRow = (index: number, patch: Partial<ReceiptRow>) =>
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  const active = lists.find((entry) => String(entry.id) === selected);
  const needed =
    active?.items.filter((item) => item.status === "needed").length ?? 0;
  const total = receiptTotal(rows);

  return (
    <div className="page">
      <PageHeader motif="flor" title="Compras e estoque" id="shopping-title">
        {active
          ? `${active.name}: ${needed} ${needed === 1 ? "item falta" : "itens faltam"}`
          : "Listas, compras e despensa"}
      </PageHeader>
      <SectionNav
        label="Seções de compras"
        sections={[
          { id: "listas", label: "Lista" },
          ...(readOnly ? [] : [{ id: "compra", label: "Compra" }]),
          { id: "estoque", label: "Estoque" },
          { id: "catalogo", label: "Catálogo" },
        ]}
      />
      {error && <ErrorNote>{error}</ErrorNote>}
      {loading ? (
        <div className="tile-wall">
          <section className="tile">
            <Loading label="Carregando…" lines={4} />
          </section>
        </div>
      ) : (
        <div className="tile-wall module-grid">
          <div className="col">
            <TileSection title="Listas compartilhadas" id="listas" order={1}>
              {lists.length ? (
                <>
                  <NativeSelect
                    label="Lista"
                    value={selected}
                    onChange={(event) => setSelected(event.currentTarget.value)}
                    data={lists.map((entry) => ({
                      value: String(entry.id),
                      label: `${entry.name} · ${LIST_STATUS[entry.status] ?? entry.status}`,
                    }))}
                    mb="sm"
                  />
                  {active?.items.length ? (
                    <ul className="rows">
                      {active.items.map((item) => (
                        <li
                          key={item.id}
                          className="row"
                          data-done={item.status !== "needed" || undefined}
                        >
                          <FlipTile
                            done={item.status === "purchased"}
                            motif="flor"
                          />
                          <span className="row-main">
                            <span className="row-title">{item.name}</span>
                            <span className="row-meta">
                              {quantity(item.quantity)} {item.unit}
                            </span>
                          </span>
                          {!readOnly && item.status === "needed" ? (
                            <span className="row-actions">
                              <Button
                                size="sm"
                                variant="light"
                                onClick={() =>
                                  void updateListItem(item.id, "purchased")
                                }
                              >
                                Marcar comprado
                              </Button>
                              <Button
                                size="sm"
                                variant="subtle"
                                color="gray"
                                onClick={() =>
                                  void updateListItem(item.id, "skipped")
                                }
                              >
                                Ignorar item
                              </Button>
                            </span>
                          ) : (
                            <Badge
                              variant="light"
                              color={
                                item.status === "purchased" ? "azulejo" : "gray"
                              }
                            >
                              {ITEM_STATUS[item.status] ?? item.status}
                            </Badge>
                          )}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState>Esta lista ainda não tem itens.</EmptyState>
                  )}
                </>
              ) : (
                <EmptyState>Nenhuma lista criada.</EmptyState>
              )}
              {!readOnly && active && (
                <form
                  className="add-item"
                  onSubmit={(event) =>
                    void submit(
                      event,
                      `/shopping-lists/${active.id}/items`,
                      (data) => ({
                        product_id: data.get("product_id") || null,
                        free_text_name: data.get("free_text_name"),
                        quantity: data.get("quantity"),
                        unit: data.get("unit"),
                      }),
                      "Item adicionado.",
                    )
                  }
                >
                  <Text fw={700} size="sm" className="add-item-title">
                    Adicionar à lista
                  </Text>
                  <NativeSelect
                    label="Produto do catálogo"
                    name="product_id"
                    data={[
                      { value: "", label: "Item livre" },
                      ...products.map((product) => ({
                        value: String(product.id),
                        label: product.name,
                      })),
                    ]}
                  />
                  <TextInput
                    label="Nome livre (se aplicável)"
                    name="free_text_name"
                  />
                  <div className="pair">
                    <TextInput
                      label="Quantidade"
                      name="quantity"
                      type="number"
                      min="0.0001"
                      step="0.0001"
                      defaultValue="1"
                      required
                    />
                    <TextInput
                      label="Unidade"
                      name="unit"
                      placeholder="un, kg, L…"
                      required
                    />
                  </div>
                  <Button
                    type="submit"
                    variant="light"
                    leftSection={<IconPlus size={16} aria-hidden="true" />}
                  >
                    Adicionar item
                  </Button>
                </form>
              )}
              {!readOnly && (
                <form
                  className="inline-form new-list"
                  onSubmit={(event) =>
                    void submit(
                      event,
                      `/households/${householdId}/shopping-lists`,
                      (data) => ({ name: data.get("name") }),
                      "Lista criada.",
                    )
                  }
                >
                  <TextInput
                    label="Nova lista"
                    name="name"
                    placeholder="Ex.: Feira de sábado"
                    required
                  />
                  <Button type="submit" variant="default">
                    Criar lista
                  </Button>
                </form>
              )}
            </TileSection>

            <TileSection title="Saldo em estoque" id="estoque" order={3}>
              {stock.length ? (
                <ul className="rows rows-compact stock">
                  {stock.map((entry) => (
                    <li
                      key={`${entry.product_id}-${entry.unit}`}
                      className="row"
                    >
                      <span className="row-main">{entry.name}</span>
                      <span className="amount">
                        {quantity(entry.quantity)} <small>{entry.unit}</small>
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState>
                  Estoque vazio. Ele se enche quando uma compra é registrada.
                </EmptyState>
              )}
            </TileSection>
          </div>

          <div className="col">
            {!readOnly && (
              <TileSection title="Confirmar compra" id="compra" order={2}>
                <Text size="sm" c="dimmed" mb="sm">
                  O total será lançado uma vez nas finanças e os itens
                  atualizarão o estoque.
                </Text>
                <form
                  className="stack"
                  onSubmit={(event) => void confirmPurchase(event)}
                >
                  {rows.map((row, index) => (
                    <fieldset key={index} className="receipt-row">
                      <legend>Item {index + 1}</legend>
                      <NativeSelect
                        label="Produto"
                        required
                        value={row.product_id}
                        onChange={(event) =>
                          setRow(index, {
                            product_id: event.currentTarget.value,
                          })
                        }
                        data={[
                          { value: "", label: "Selecione" },
                          ...products.map((product) => ({
                            value: String(product.id),
                            label: product.name,
                          })),
                        ]}
                      />
                      <div className="trio">
                        <TextInput
                          label="Quantidade"
                          inputMode="decimal"
                          value={row.quantity}
                          onChange={(event) =>
                            setRow(index, {
                              quantity: event.currentTarget.value,
                            })
                          }
                          required
                        />
                        <TextInput
                          label="Unidade"
                          name={`unit-${index}`}
                          value={
                            products.find(
                              (product) =>
                                String(product.id) === row.product_id,
                            )?.unit ?? "un"
                          }
                          readOnly
                          required
                        />
                        <TextInput
                          label="Preço unitário (R$)"
                          inputMode="decimal"
                          placeholder="0,00"
                          value={row.price}
                          onChange={(event) =>
                            setRow(index, { price: event.currentTarget.value })
                          }
                          required
                        />
                      </div>
                      {rows.length > 1 && (
                        <ActionIcon
                          variant="subtle"
                          color="barro"
                          aria-label={`Remover item ${index + 1}`}
                          className="receipt-remove"
                          onClick={() =>
                            setRows((current) =>
                              current.filter((_, i) => i !== index),
                            )
                          }
                        >
                          <IconTrash size={16} />
                        </ActionIcon>
                      )}
                    </fieldset>
                  ))}
                  <Button
                    variant="subtle"
                    leftSection={<IconPlus size={16} aria-hidden="true" />}
                    onClick={() =>
                      setRows((current) => [...current, blankRow()])
                    }
                  >
                    Adicionar item
                  </Button>
                  <TextInput
                    label="Loja"
                    name="store_name"
                    description="Opcional"
                  />
                  <div className="receipt-total" aria-live="polite">
                    <span>Total</span>
                    <strong className="amount">
                      {total === null ? "—" : money(total)}
                    </strong>
                  </div>
                  <Button
                    type="submit"
                    loading={busy}
                    disabled={!products.length}
                    leftSection={<IconReceipt size={16} aria-hidden="true" />}
                  >
                    Registrar compra
                  </Button>
                </form>
              </TileSection>
            )}

            <TileSection title="Catálogo" id="catalogo" order={4}>
              {products.length ? (
                <ul className="rows rows-compact">
                  {products.map((product) => (
                    <li key={product.id} className="row">
                      <span className="row-main">
                        <span className="row-title">{product.name}</span>
                        {(product.brand || product.category) && (
                          <span className="row-meta">
                            {[product.brand, product.category]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        )}
                      </span>
                      <Badge variant="outline" color="gray" size="sm">
                        {product.unit}
                      </Badge>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyState>Nenhum produto cadastrado.</EmptyState>
              )}
              {!readOnly && (
                <form
                  className="stack catalog-form"
                  onSubmit={(event) =>
                    void submit(
                      event,
                      `/households/${householdId}/products`,
                      (data) => ({
                        name: data.get("name"),
                        brand: data.get("brand"),
                        category: data.get("category"),
                        unit: data.get("unit"),
                      }),
                      "Produto cadastrado.",
                    )
                  }
                >
                  <TextInput label="Nome" name="name" required />
                  <div className="pair">
                    <TextInput
                      label="Marca"
                      name="brand"
                      description="Opcional"
                    />
                    <TextInput
                      label="Categoria"
                      name="category"
                      description="Opcional"
                    />
                  </div>
                  <TextInput
                    label="Unidade"
                    name="unit"
                    placeholder="un, kg, L…"
                    required
                  />
                  <Button type="submit" variant="light">
                    Cadastrar produto
                  </Button>
                </form>
              )}
            </TileSection>
          </div>
        </div>
      )}
    </div>
  );
}
