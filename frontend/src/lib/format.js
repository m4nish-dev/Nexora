const integer = new Intl.NumberFormat("en-US");

export const formatInt = (n) => (Number.isFinite(n) ? integer.format(n) : "—");

export function formatTime(date) {
  return new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" }).format(date);
}

/** "gemini/gemini-3.5-flash-lite" -> { provider: "gemini", name: "gemini-3.5-flash-lite" } */
export function splitModel(model = "") {
  const i = model.indexOf("/");
  return i === -1 ? { provider: "", name: model } : { provider: model.slice(0, i), name: model.slice(i + 1) };
}

export function shortSessionId(id = "") {
  const raw = id.replace(/^s-/, "");
  return raw.length > 8 ? `${raw.slice(0, 4)}…${raw.slice(-4)}` : raw;
}
