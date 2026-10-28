/** Formats integer cents as BRL, keeping the sign for values under one real. */
export function money(cents: number | null | undefined) {
  const value = Number.isFinite(cents) ? (cents as number) : 0;
  const absolute = Math.abs(value);
  const major = String(Math.trunc(absolute / 100)).replace(
    /\B(?=(\d{3})+(?!\d))/g,
    ".",
  );
  return `R$ ${value < 0 ? "-" : ""}${major},${String(absolute % 100).padStart(2, "0")}`;
}

/** Parses "1.234,56", "R$ 10" or "10.5" into integer cents; null when invalid. */
export function parseMoney(value: string): number | null {
  const normalized = value
    .trim()
    .replace(/^R\$\s*/, "")
    .replace(/\./g, "")
    .replace(",", ".");
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  const cents = `${fraction}00`.slice(0, 2);
  const result = `${whole}${cents}`.replace(/^0+(?=\d)/, "");
  if (result.length > 15) return null;
  return result
    .split("")
    .reduce((amount, digit) => amount * 10 + digit.charCodeAt(0) - 48, 0);
}

/** Strict unit price parser used for purchase receipts. */
export function currencyToMinor(text: string): number {
  const match = text.trim().match(/^(\d+)(?:[,.](\d{1,2}))?$/);
  if (!match)
    throw new Error("Informe um preço válido com até duas casas decimais.");
  const cents =
    BigInt(match[1]) * 100n + BigInt((match[2] ?? "").padEnd(2, "0") || "0");
  if (cents <= 0n || cents > BigInt(Number.MAX_SAFE_INTEGER))
    throw new Error("Preço fora do limite permitido.");
  return Number(cents);
}

export const DEFAULT_TIME_ZONE = "America/Sao_Paulo";

function dateParts(date: Date, timeZone = DEFAULT_TIME_ZONE) {
  return Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  );
}

export function localDay(date = new Date(), timeZone = DEFAULT_TIME_ZONE) {
  const { year, month, day } = dateParts(date, timeZone);
  return `${year}-${month}-${day}`;
}

export function localPeriod(date = new Date(), timeZone = DEFAULT_TIME_ZONE) {
  const { year, month } = dateParts(date, timeZone);
  return `${year}-${month}`;
}

export function dateTime(iso: string, timeZone?: string) {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    ...(timeZone ? { timeZone } : {}),
  }).format(new Date(iso));
}

export function monthName(period: string) {
  const [year, month] = period.split("-").map(Number);
  const name = new Intl.DateTimeFormat("pt-BR", { month: "long" }).format(
    new Date(year, month - 1, 1),
  );
  return `${name} de ${year}`;
}

export function today(timeZone = DEFAULT_TIME_ZONE) {
  return new Intl.DateTimeFormat("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone,
  }).format(new Date());
}

export function quantity(value: string) {
  const number = Number(value);
  return Number.isFinite(number)
    ? new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 }).format(
        number,
      )
    : value;
}

/** "2026-10-25" as "25/10/2026" without a timezone shift. */
export function isoDay(day: string) {
  const [year, month, date] = day.split("-");
  return year && month && date ? `${date}/${month}/${year}` : day;
}
