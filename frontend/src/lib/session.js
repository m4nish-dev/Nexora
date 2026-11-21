/** Client-generated session ids. A fresh one is created on every page load (contract §5). */

function randomHex(bytes) {
  const buf = new Uint8Array(bytes);
  crypto.getRandomValues(buf);
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function createSessionId() {
  // crypto.randomUUID needs a secure context; getRandomValues works everywhere.
  const id = typeof crypto.randomUUID === "function" && window.isSecureContext ? crypto.randomUUID() : randomHex(16);
  return `s-${id}`;
}
