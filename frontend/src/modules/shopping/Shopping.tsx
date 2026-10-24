import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
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
type List = { id: number; name: string; status: string; items: Item[] };
type Stock = {
  product_id: number;
  name: string;
  quantity: string;
  unit: string;
};
type ReceiptRow = { product_id: string; quantity: string; price: string };

function currencyToMinor(text: string): number {
  const match = text.trim().match(/^(\d+)(?:[,.](\d{1,2}))?$/);
  if (!match)
    throw new Error("Informe um preço válido com até duas casas decimais.");
  const cents =
    BigInt(match[1]) * 100n + BigInt((match[2] ?? "").padEnd(2, "0") || "0");
  if (
    cents <= 0n ||
    cents > 9223372036854775807n ||
    cents > BigInt(Number.MAX_SAFE_INTEGER)
  )
    throw new Error("Preço fora do limite permitido.");
  return Number(cents);
}

async function call<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      data.detail ??
        Object.values(data).flat().join(" ") ??
        "Falha na solicitação.",
    );
  return data as T;
}

export default function Shopping({
  householdId,
  role,
}: {
  householdId: string;
  role: string;
}) {
  const [products, setProducts] = useState<Product[]>([]);
  const [lists, setLists] = useState<List[]>([]);
  const [stock, setStock] = useState<Stock[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [receiptRows, setReceiptRows] = useState<ReceiptRow[]>([
    { product_id: "", quantity: "1", price: "" },
  ]);
  const readOnly = role === "viewer";
  const pendingPurchase = useRef<{ payload: string; key: string } | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      const [p, l, s] = await Promise.all([
        call<Product[]>(`/households/${householdId}/products`),
        call<List[]>(`/households/${householdId}/shopping-lists`),
        call<Stock[]>(`/households/${householdId}/inventory`),
      ]);
      setProducts(p);
      setLists(l);
      setStock(s);
      if (!selected && l.length) setSelected(String(l[0].id));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Não foi possível carregar os dados.",
      );
    } finally {
      setBusy(false);
    }
  }, [householdId, selected]);
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
    setMessage("");
    try {
      const csrf = await call<{ csrfToken: string }>("/auth/csrf");
      await call(path, {
        method: "POST",
        headers: { "X-CSRFToken": csrf.csrfToken },
        body: JSON.stringify(build(new FormData(form))),
      });
      form.reset();
      setMessage(success);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao salvar.");
    }
  }

  async function confirmPurchase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const purchasePayload = {
      purchased_at: (() => {
        const now = new Date();
        return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      })(),
      store_name: data.get("store_name"),
      items: receiptRows.map((row, index) => ({
        product_id: Number(row.product_id),
        quantity: row.quantity,
        unit: String(data.get(`unit-${index}`)),
        unit_price_minor: currencyToMinor(row.price),
      })),
    };
    const encodedPayload = JSON.stringify(purchasePayload);
    if (
      !pendingPurchase.current ||
      pendingPurchase.current.payload !== encodedPayload
    )
      pendingPurchase.current = {
        payload: encodedPayload,
        key: crypto.randomUUID(),
      };
    setBusy(true);
    setError("");
    try {
      const csrf = await call<{ csrfToken: string }>("/auth/csrf");
      const response = await call<{ id: number }>(
        `/households/${householdId}/purchases`,
        {
          method: "POST",
          headers: {
            "X-CSRFToken": csrf.csrfToken,
            "Idempotency-Key": pendingPurchase.current.key,
          },
          body: encodedPayload,
        },
      );
      form.reset();
      pendingPurchase.current = null;
      setReceiptRows([{ product_id: "", quantity: "1", price: "" }]);
      setMessage(
        `Compra ${response.id} registrada; estoque e financeiro atualizados.`,
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao confirmar a compra.");
    } finally {
      setBusy(false);
    }
  }

  const list = lists.find((entry) => String(entry.id) === selected);
  return (
    <section className="shopping-module" aria-labelledby="shopping-title">
      <p className="eyebrow">COMPRAS · ESTOQUE</p>
      <h1 id="shopping-title">Compras e estoque</h1>
      {busy && <p role="status">Carregando…</p>}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      <div className="house-list">
        <section className="house-card">
          <div>
            <h2>Catálogo</h2>
            {products.length ? (
              <ul>
                {products.map((p) => (
                  <li key={p.id}>
                    {p.name} — {p.unit}
                    {p.brand && ` · ${p.brand}`}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">Nenhum produto cadastrado.</p>
            )}
            {!readOnly && (
              <form
                className="form-stack"
                onSubmit={(e) =>
                  void submit(
                    e,
                    `/households/${householdId}/products`,
                    (d) => ({
                      name: d.get("name"),
                      brand: d.get("brand"),
                      category: d.get("category"),
                      unit: d.get("unit"),
                    }),
                    "Produto cadastrado.",
                  )
                }
              >
                <label>
                  Nome
                  <input name="name" required />
                </label>
                <label>
                  Marca
                  <input name="brand" />
                </label>
                <label>
                  Categoria
                  <input name="category" />
                </label>
                <label>
                  Unidade
                  <input name="unit" placeholder="un, kg, L…" required />
                </label>
                <button>Cadastrar produto</button>
              </form>
            )}
          </div>
        </section>
        <section className="house-card">
          <div>
            <h2>Listas compartilhadas</h2>
            {lists.length ? (
              <>
                <label>
                  Lista
                  <select
                    value={selected}
                    onChange={(e) => setSelected(e.target.value)}
                  >
                    {lists.map((l) => (
                      <option key={l.id} value={l.id}>
                        {l.name} · {l.status}
                      </option>
                    ))}
                  </select>
                </label>
                <ul>
                  {list?.items.map((item) => (
                    <li key={item.id}>
                      {item.name} — {item.quantity} {item.unit} · {item.status}
                      {!readOnly && item.status === "needed" && (
                        <>
                          <button
                            type="button"
                            onClick={() =>
                              void updateListItem(item.id, "purchased")
                            }
                          >
                            Marcar comprado
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              void updateListItem(item.id, "skipped")
                            }
                          >
                            Ignorar item
                          </button>
                        </>
                      )}
                    </li>
                  ))}
                </ul>
                {!list?.items.length && (
                  <p className="empty">Esta lista ainda não tem itens.</p>
                )}
              </>
            ) : (
              <p className="empty">Nenhuma lista criada.</p>
            )}
            {!readOnly && (
              <>
                <form
                  className="create-house"
                  onSubmit={(e) =>
                    void submit(
                      e,
                      `/households/${householdId}/shopping-lists`,
                      (d) => ({ name: d.get("name") }),
                      "Lista criada.",
                    )
                  }
                >
                  <label>
                    Nova lista
                    <input name="name" required />
                  </label>
                  <button>Criar lista</button>
                </form>
                {list && (
                  <form
                    className="form-stack"
                    onSubmit={(e) =>
                      void submit(
                        e,
                        `/shopping-lists/${list.id}/items`,
                        (d) => ({
                          product_id: d.get("product_id") || null,
                          free_text_name: d.get("free_text_name"),
                          quantity: d.get("quantity"),
                          unit: d.get("unit"),
                        }),
                        "Item adicionado.",
                      )
                    }
                  >
                    <label>
                      Produto
                      <select name="product_id">
                        <option value="">Item livre</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Nome livre (se aplicável)
                      <input name="free_text_name" />
                    </label>
                    <label>
                      Quantidade
                      <input
                        name="quantity"
                        type="number"
                        min="0.0001"
                        step="0.0001"
                        defaultValue="1"
                        required
                      />
                    </label>
                    <label>
                      Unidade
                      <input name="unit" required />
                    </label>
                    <button>Adicionar item</button>
                  </form>
                )}
              </>
            )}
          </div>
        </section>
        <section className="house-card">
          <div>
            <h2>Confirmar compra</h2>
            <p>
              O total será lançado uma vez nas finanças e os itens atualizarão o
              estoque.
            </p>
            {!readOnly && (
              <form
                className="form-stack"
                onSubmit={(e) => void confirmPurchase(e)}
              >
                {receiptRows.map((row, index) => (
                  <fieldset key={index}>
                    <legend>Item {index + 1}</legend>
                    <label>
                      Produto
                      <select
                        required
                        value={row.product_id}
                        onChange={(e) =>
                          setReceiptRows((rows) =>
                            rows.map((r, i) =>
                              i === index
                                ? { ...r, product_id: e.target.value }
                                : r,
                            ),
                          )
                        }
                      >
                        <option value="">Selecione</option>
                        {products.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Quantidade
                      <input
                        type="text"
                        inputMode="decimal"
                        value={row.quantity}
                        onChange={(e) =>
                          setReceiptRows((rows) =>
                            rows.map((r, i) =>
                              i === index
                                ? { ...r, quantity: e.target.value }
                                : r,
                            ),
                          )
                        }
                        required
                      />
                    </label>
                    <label>
                      Unidade
                      <input
                        name={`unit-${index}`}
                        value={
                          products.find((p) => String(p.id) === row.product_id)
                            ?.unit ?? "un"
                        }
                        readOnly
                        required
                      />
                    </label>
                    <label>
                      Preço unitário (R$)
                      <input
                        type="text"
                        inputMode="decimal"
                        value={row.price}
                        onChange={(e) =>
                          setReceiptRows((rows) =>
                            rows.map((r, i) =>
                              i === index ? { ...r, price: e.target.value } : r,
                            ),
                          )
                        }
                        required
                      />
                    </label>
                    {receiptRows.length > 1 && (
                      <button
                        type="button"
                        onClick={() =>
                          setReceiptRows((rows) =>
                            rows.filter((_, i) => i !== index),
                          )
                        }
                      >
                        Remover item
                      </button>
                    )}
                  </fieldset>
                ))}
                <button
                  type="button"
                  onClick={() =>
                    setReceiptRows((rows) => [
                      ...rows,
                      { product_id: "", quantity: "1", price: "" },
                    ])
                  }
                >
                  Adicionar item
                </button>
                <label>
                  Loja
                  <input name="store_name" />
                </label>
                <button disabled={busy || !products.length}>
                  Registrar compra
                </button>
              </form>
            )}
          </div>
        </section>
        <section className="house-card">
          <div>
            <h2>Saldo em estoque</h2>
            {stock.length ? (
              <ul>
                {stock.map((entry) => (
                  <li key={`${entry.product_id}-${entry.unit}`}>
                    {entry.name}: {entry.quantity} {entry.unit}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="empty">Estoque vazio.</p>
            )}
          </div>
        </section>
      </div>
    </section>
  );

  async function updateListItem(itemId: number, status: string) {
    setError("");
    try {
      const csrf = await call<{ csrfToken: string }>("/auth/csrf");
      await call(`/shopping-items/${itemId}`, {
        method: "PATCH",
        headers: { "X-CSRFToken": csrf.csrfToken },
        body: JSON.stringify({ status }),
      });
      setMessage(
        status === "purchased"
          ? "Item marcado como comprado."
          : "Item ignorado.",
      );
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao atualizar o item.");
    }
  }
}
