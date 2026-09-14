const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function longDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
}

export function shortDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCDate()}`;
}

export function clockUTC(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

/** Timestamps arrive with a Z from one writer and a +00:00 offset from another. */
export function stampUTC(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

export function dayKey(iso: string): string {
  return iso.slice(0, 10);
}

export function ago(iso: string, now = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const mins = Math.max(0, Math.round((now - then) / 60_000));
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  if (days < 60) return `${days} days ago`;
  return `${Math.round(days / 30)} months ago`;
}

export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not recorded";
  return `$${value.toFixed(2)}`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** First sentence of a CPSC hazard paragraph, which is where the danger itself is stated. */
export function firstSentence(text: string, limit = 220): string {
  const clean = text.replace(/\s+/g, " ").trim();
  const stop = clean.search(/\.\s|\.$/);
  const sentence = stop > 40 ? clean.slice(0, stop + 1) : clean;
  return sentence.length > limit ? `${sentence.slice(0, limit).trimEnd()}...` : sentence;
}

const REMEDY_WORDS: Record<string, string> = {
  refund: "a refund",
  replace: "a free replacement",
  repair: "a free repair",
  destroy: "disposal",
  stop_use: "stopping use",
};

export function remedyPhrase(kinds: string[]): string {
  const paid = kinds.filter((k) => k === "refund" || k === "replace" || k === "repair");
  const list = (paid.length ? paid : kinds).map((k) => REMEDY_WORDS[k] ?? k);
  if (list.length === 0) return "the remedy in the notice";
  if (list.length === 1) return list[0];
  return `${list.slice(0, -1).join(", ")} or ${list[list.length - 1]}`;
}
