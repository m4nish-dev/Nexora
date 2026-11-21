/**
 * Browser tests for the UI contract (assignment §5) plus core behaviour.
 *
 *   E2E_URL=http://localhost:3100 E2E_MODE=fake node e2e/contract.e2e.mjs
 *
 * E2E_MODE=fake  → backend is backend/tests/e2e_server.py (deterministic; enables reply-content checks).
 * E2E_MODE=live  → any real stack (e.g. `make up` with real keys); only provider-agnostic checks run.
 * Screenshots are written to E2E_SCREENSHOTS (default: e2e/screenshots).
 */
import { mkdirSync } from "node:fs";
import { chromium } from "playwright";

const URL = process.env.E2E_URL || "http://localhost:3100";
const MODE = process.env.E2E_MODE || "fake";
const SHOTS = process.env.E2E_SCREENSHOTS || new globalThis.URL("./screenshots", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push({ name, ok: true });
    console.log(`  \u001b[32mPASS\u001b[0m ${name}`);
  } catch (err) {
    results.push({ name, ok: false });
    console.log(`  \u001b[31mFAIL\u001b[0m ${name}\n       ${String(err.message).split("\n")[0]}`);
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const browser = await chromium.launch();
const runId = Date.now().toString(36);
const appErrors = [];

async function openApp(viewport = { width: 1440, height: 900 }) {
  const page = await browser.newPage({ viewport });
  page.on("pageerror", (e) => appErrors.push(String(e)));
  await page.goto(URL);
  await page.waitForSelector('[data-testid="backend-status"]:has-text("Online")', { timeout: 15000 });
  return page;
}
const assistant = (page, i) => page.getByTestId("assistant-message").nth(i);
async function sendAndWait(page, text, index, how = "enter") {
  await page.getByTestId("chat-input").fill(text);
  if (how === "enter") await page.getByTestId("chat-input").press("Enter");
  else await page.getByTestId("send-button").click();
  await assistant(page, index).waitFor({ timeout: 60000 });
  return assistant(page, index);
}

console.log(`Nexora UI e2e — ${URL} (mode: ${MODE})`);
const page = await openApp();
await page.screenshot({ path: `${SHOTS}/desktop-welcome.png` });
const firstQuestion = `How does response caching work? [${runId}]`;
let sessionA;

await test("required data-testids are present", async () => {
  for (const id of ["chat-input", "send-button", "system-prompt-input"]) {
    assert((await page.getByTestId(id).count()) === 1, `missing ${id}`);
  }
});

await test("Enter sends; input clears; reply carries per-request metadata", async () => {
  sessionA = await page.getByTestId("session-id").getAttribute("title");
  await page.getByTestId("chat-input").fill(firstQuestion);
  await page.getByTestId("chat-input").press("Enter");
  assert((await page.getByTestId("chat-input").inputValue()) === "", "chat-input not cleared");
  await page.getByTestId("typing-indicator").waitFor({ timeout: 5000 });
  const m = assistant(page, 0);
  await m.waitFor({ timeout: 60000 });
  assert((await m.getByTestId("meta-source").textContent()) === "LIVE_INFERENCE", "first reply not LIVE_INFERENCE");
  assert(/\S/.test(await m.getByTestId("meta-model").textContent()), "empty meta-model");
  assert(/^\d+ ms$/.test(await m.getByTestId("meta-latency").textContent()), "meta-latency not '<n> ms'");
  assert(/^\d+$/.test(await m.getByTestId("meta-input-tokens").textContent()), "meta-input-tokens not an integer");
  assert(/^\d+$/.test(await m.getByTestId("meta-output-tokens").textContent()), "meta-output-tokens not an integer");
  await page.screenshot({ path: `${SHOTS}/desktop-first-reply.png` });
});

await test("Shift+Enter inserts a newline; send button sends", async () => {
  await page.getByTestId("chat-input").click();
  await page.keyboard.type("line one");
  await page.keyboard.press("Shift+Enter");
  await page.keyboard.type("line two");
  assert((await page.getByTestId("chat-input").inputValue()) === "line one\nline two", "newline not inserted");
  await page.getByTestId("send-button").click();
  await assistant(page, 1).waitFor({ timeout: 60000 });
  const metaCount = await page.locator('[data-testid="assistant-message"] [data-testid="meta-source"]').count();
  assert(metaCount === 2, `expected one meta-source per reply, got ${metaCount}`);
  if (MODE === "fake") assert((await assistant(page, 1).textContent()).includes("turn 2"), "history not sent to backend");
});

await test("multi-turn: input tokens grow with history (per request, not totals)", async () => {
  const first = Number(await assistant(page, 0).getByTestId("meta-input-tokens").textContent());
  const second = Number(await assistant(page, 1).getByTestId("meta-input-tokens").textContent());
  assert(second > first, `turn-2 input tokens (${second}) should exceed turn-1 (${first})`);
});

await test("failover lab: key_1=429 → real reply from key_2", async () => {
  await page.getByRole("radio", { name: /key_1 → 429/ }).click();
  const m = await sendAndWait(page, `Failover check ${runId}`, 2, "click");
  assert((await m.getByTestId("meta-key-id").textContent()) === "key_2", "not answered by key_2");
  assert((await m.getByTestId("meta-fallback-attempts").count()) === 1, "no failover chip");
  assert((await m.getByTestId("meta-source").textContent()) === "LIVE_INFERENCE", "simulated request served from cache");
});

await test("all keys failing → readable 503 message, Retry recovers", async () => {
  await page.getByRole("radio", { name: /All keys → 429/ }).click();
  await page.getByTestId("chat-input").fill(`All fail ${runId}`);
  await page.getByTestId("send-button").click();
  const err = page.getByTestId("error-message");
  await err.waitFor({ timeout: 30000 });
  assert(/All providers unavailable/.test(await err.textContent()), "503 message not readable");
  await page.screenshot({ path: `${SHOTS}/desktop-error-503.png` });
  await page.getByRole("button", { name: "Retry" }).click();
  await assistant(page, 3).waitFor({ timeout: 60000 });
  assert((await page.getByTestId("error-message").count()) === 0, "error card not removed after retry");
});

await test("over-long message → readable 422 message", async () => {
  await page.getByTestId("chat-input").fill("x".repeat(4001));
  await page.getByTestId("send-button").click();
  const err = page.getByTestId("error-message");
  await err.waitFor({ timeout: 30000 });
  assert(/Request rejected/.test(await err.textContent()), "422 message not readable");
});

await test("system prompt applies and Reset restores the default in the same session", async () => {
  await page.getByRole("button", { name: /System prompt/ }).click();
  await page.getByTestId("system-prompt-input").fill("Answer like a pirate.");
  await page.getByRole("button", { name: "Apply" }).click();
  const custom = await sendAndWait(page, `Prompt check ${runId}`, 4);
  if (MODE === "fake") assert((await custom.textContent()).includes("Arr!"), "custom system prompt not applied");
  await page.getByRole("button", { name: "Reset" }).click();
  const reset = await sendAndWait(page, `Prompt reset check ${runId}`, 5);
  if (MODE === "fake") assert(!(await reset.textContent()).includes("Arr!"), "Reset did not restore the default prompt");
});

await test("history endpoint matches the conversation (only successful turns)", async () => {
  const api = await page.evaluate(() => window.__NEXORA_CONFIG__?.API_BASE_URL || "");
  const base = api || (MODE === "fake" ? "http://localhost:8100" : "http://localhost:8000");
  const res = await page.request.get(`${base}/sessions/${encodeURIComponent(sessionA)}/messages`);
  assert(res.status() === 200, `history status ${res.status()}`);
  const body = await res.json();
  assert(body.messages.length === 12, `expected 12 stored messages (6 successful turns), got ${body.messages.length}`);
  assert(body.messages[0].content === firstQuestion, "oldest message not first");
});

await test("reload starts a new session; same first message → LLM_CACHE", async () => {
  await page.reload();
  await page.waitForSelector('[data-testid="backend-status"]:has-text("Online")');
  const sessionB = await page.getByTestId("session-id").getAttribute("title");
  assert(sessionB && sessionB !== sessionA, "session id did not change on reload");
  assert((await page.getByTestId("assistant-message").count()) === 0, "old messages still shown");
  const m = await sendAndWait(page, firstQuestion, 0);
  assert((await m.getByTestId("meta-source").textContent()) === "LLM_CACHE", "not served from cache");
  const ms = Number((await m.getByTestId("meta-latency").textContent()).replace(" ms", ""));
  assert(ms < 200, `cache hit latency ${ms} ms is not fast`);
  assert((await m.getByTestId("meta-key-id").count()) === 0, "cache hit should have no key_id");
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${SHOTS}/desktop-cache-hit.png` });
});

await test("dark theme renders", async () => {
  await page.getByRole("radio", { name: "Dark" }).click();
  await page.waitForTimeout(400);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  assert(bg === "rgb(11, 11, 13)", `unexpected dark background ${bg}`);
  await page.screenshot({ path: `${SHOTS}/desktop-dark.png` });
  await page.getByRole("radio", { name: "Light" }).click();
});

await test("mobile: chat works, drawer opens, no horizontal overflow", async () => {
  const mobile = await openApp({ width: 390, height: 844 });
  await sendAndWait(mobile, `Mobile check ${runId}`, 0, "click");
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  assert(!overflow, "horizontal overflow on mobile");
  await mobile.screenshot({ path: `${SHOTS}/mobile-reply.png` });
  await mobile.getByRole("button", { name: "Open sidebar" }).click();
  await mobile.getByRole("button", { name: "Close sidebar" }).waitFor();
  await mobile.waitForTimeout(400);
  await mobile.screenshot({ path: `${SHOTS}/mobile-drawer.png` });
  await mobile.keyboard.press("Escape");
  await mobile.close();
});

await test("tablet layout has no horizontal overflow", async () => {
  const tablet = await openApp({ width: 820, height: 1180 });
  const overflow = await tablet.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  assert(!overflow, "horizontal overflow on tablet");
  await tablet.screenshot({ path: `${SHOTS}/tablet.png` });
  await tablet.close();
});

await test("no uncaught page errors", async () => {
  assert(appErrors.length === 0, appErrors.slice(0, 2).join(" | "));
});

await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed} passed, ${failed} failed. Screenshots: ${SHOTS}`);
process.exit(failed ? 1 : 0);
