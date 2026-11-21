import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  Cpu,
  Database,
  FlaskConical,
  KeyRound,
  Moon,
  Plus,
  RefreshCw,
  Server,
  Sun,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import { Button, CopyButton, cx, IconButton, LogoMark, SectionLabel, StatusDot } from "./ui/primitives";
import { formatTime, shortSessionId, splitModel } from "../lib/format";

const SYSTEM_PROMPT_MAX = 8000;

const SIMULATION_PRESETS = [
  { value: "key_1=429", label: "key_1 → 429", hint: "Rate-limit the first key" },
  { value: "key_1=500", label: "key_1 → 500", hint: "Server error on the first key" },
  { value: "*=429", label: "All keys → 429", hint: "Every key fails → 503" },
];

function StatusRow({ icon: Icon, label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 px-1 py-1.5 text-[13px]">
      <span className="flex items-center gap-2 text-fg-muted">
        <Icon className="size-3.5 text-fg-faint" aria-hidden="true" />
        {label}
      </span>
      <span className="flex min-w-0 items-center gap-1.5 text-right text-fg">{children}</span>
    </div>
  );
}

function SystemStatus({ health }) {
  const { status, data, latencyMs, refresh, checkedAt } = health;
  const tone = { online: "ok", degraded: "warn", offline: "danger", checking: "neutral" }[status];
  const label = { online: "Online", degraded: "Degraded", offline: "Offline", checking: "Checking" }[status];
  const models = data?.models ?? [];

  return (
    <section>
      <SectionLabel
        action={
          <IconButton label="Re-check backend health" onClick={refresh} className="size-6">
            <RefreshCw className={cx("size-3", status === "checking" && "animate-spin")} />
          </IconButton>
        }
      >
        System
      </SectionLabel>
      <div className="rounded-xl border border-line bg-panel px-2.5 py-1.5 shadow-card">
        <StatusRow icon={Server} label="Backend">
          <StatusDot tone={tone} pulse={status === "online"} />
          <span data-testid="backend-status">{label}</span>
          {latencyMs != null && <span className="font-mono text-xs text-fg-faint">{latencyMs}ms</span>}
        </StatusRow>
        <StatusRow icon={Cpu} label="Model">
          <span className="truncate font-mono text-xs" title={models.join(", ")}>
            {models.length ? splitModel(models[0]).name + (models.length > 1 ? ` +${models.length - 1}` : "") : "—"}
          </span>
        </StatusRow>
        <StatusRow icon={KeyRound} label="Key pool">
          <span className="font-mono text-xs">{data ? `${data.keys_configured} keys` : "—"}</span>
        </StatusRow>
        <StatusRow icon={Database} label="Response cache">
          {data ? (
            <>
              <StatusDot tone={data.cache_enabled ? "ok" : "neutral"} />
              <span className="text-xs">{data.cache_enabled ? "Enabled" : "Disabled"}</span>
            </>
          ) : (
            "—"
          )}
        </StatusRow>
      </div>
      {checkedAt && <p className="mt-1.5 px-1 text-[11px] text-fg-faint">Checked {formatTime(checkedAt)}</p>}
    </section>
  );
}

function SessionCard({ sessionId, startedAt, stats }) {
  return (
    <section>
      <SectionLabel>Current session</SectionLabel>
      <div className="rounded-xl border border-line bg-panel p-3 shadow-card">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] text-fg-faint">Session ID</p>
            <p className="truncate font-mono text-[13px] text-fg" title={sessionId} data-testid="session-id">
              {shortSessionId(sessionId)}
            </p>
          </div>
          <CopyButton text={sessionId} label="Copy session ID" />
        </div>
        <div className="mt-3 grid grid-cols-3 gap-1.5 text-center">
          {[
            ["Turns", stats.turns],
            ["Cache hits", stats.cacheHits],
            ["Failovers", stats.failovers],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg bg-subtle px-1 py-1.5">
              <p className="font-mono text-sm tabular-nums text-fg">{value}</p>
              <p className="text-[10px] text-fg-faint">{label}</p>
            </div>
          ))}
        </div>
        <p className="mt-2.5 text-[11px] text-fg-faint">Started {formatTime(startedAt)} · history stored server-side</p>
      </div>
    </section>
  );
}

function SystemPromptEditor({ defaultPrompt, appliedPrompt, onApply }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(appliedPrompt || defaultPrompt || "");
  const [savedFlash, setSavedFlash] = useState(false);

  // Seed the editor once the backend's default prompt arrives.
  useEffect(() => {
    if (!appliedPrompt && defaultPrompt) setDraft((d) => d || defaultPrompt);
  }, [defaultPrompt, appliedPrompt]);

  const effective = appliedPrompt || defaultPrompt || "";
  const trimmed = draft.trim();
  const dirty = trimmed !== effective.trim();
  const isCustom = Boolean(appliedPrompt) && appliedPrompt.trim() !== (defaultPrompt || "").trim();
  const tooLong = draft.length > SYSTEM_PROMPT_MAX;

  const apply = () => {
    if (!trimmed || tooLong) return;
    onApply(trimmed === (defaultPrompt || "").trim() ? "" : trimmed);
    setSavedFlash(true);
    setTimeout(() => setSavedFlash(false), 1400);
  };

  return (
    <div className="rounded-xl border border-line bg-panel shadow-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls="system-prompt-panel"
        className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left text-[13px]"
      >
        <span className="font-medium text-fg">System prompt</span>
        <span className="flex items-center gap-2">
          <span
            className={cx(
              "rounded-md px-1.5 py-0.5 text-[10px] font-medium",
              isCustom ? "bg-accent-soft text-accent" : "bg-subtle text-fg-faint",
            )}
          >
            {isCustom ? "Custom" : "Default"}
          </span>
          <ChevronDown className={cx("size-3.5 text-fg-faint transition-transform", open && "rotate-180")} />
        </span>
      </button>
      {/* Always mounted (hidden when collapsed) so the field exists in the DOM for automation. */}
      <div id="system-prompt-panel" hidden={!open} className="border-t border-line px-3 pt-2.5 pb-3">
        <label htmlFor="system-prompt-input" className="sr-only">
          System prompt
        </label>
        <textarea
          id="system-prompt-input"
          data-testid="system-prompt-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={6}
          placeholder="Describe how the assistant should behave…"
          className={cx(
            "block w-full resize-y rounded-lg border bg-elevated px-2.5 py-2 text-[13px] leading-5 text-fg outline-none placeholder:text-fg-faint",
            tooLong ? "border-danger" : "border-line focus:border-line-strong",
          )}
        />
        <div className="mt-1.5 flex items-center justify-between text-[11px] text-fg-faint">
          <span>Applies to your next messages in this session.</span>
          <span className={cx("font-mono tabular-nums", tooLong && "text-danger")}>
            {draft.length}/{SYSTEM_PROMPT_MAX}
          </span>
        </div>
        <div className="mt-2.5 flex gap-2">
          <Button size="sm" variant="primary" onClick={apply} disabled={!dirty || !trimmed || tooLong} className="flex-1">
            {savedFlash ? <Check className="size-3.5" /> : null}
            {savedFlash ? "Applied" : "Apply"}
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setDraft(defaultPrompt || "");
              if (appliedPrompt) onApply("");
            }}
            disabled={!isCustom && !dirty}
          >
            Reset
          </Button>
        </div>
      </div>
    </div>
  );
}

function FailoverLab({ simulation, onChange }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-3 shadow-card">
      <div className="flex items-center gap-2 text-[13px] font-medium text-fg">
        <FlaskConical className="size-3.5 text-warn" aria-hidden="true" />
        Failover lab
      </div>
      <p className="mt-1 text-[11px] leading-4 text-fg-faint">
        Sends <span className="font-mono">X-Simulate-Failure</span> with your next message only.
      </p>
      <div className="mt-2.5 grid gap-1.5" role="radiogroup" aria-label="Failure simulation preset">
        {SIMULATION_PRESETS.map((preset) => {
          const active = simulation === preset.value;
          return (
            <button
              key={preset.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(active ? null : preset.value)}
              title={preset.hint}
              className={cx(
                "flex items-center justify-between rounded-lg border px-2.5 py-1.5 text-left font-mono text-xs transition-colors",
                active
                  ? "border-warn/40 bg-warn-soft text-warn"
                  : "border-line text-fg-muted hover:border-line-strong hover:text-fg",
              )}
            >
              {preset.label}
              {active && <Check className="size-3.5" aria-hidden="true" />}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ThemeSwitch({ theme, setTheme }) {
  return (
    <div className="flex items-center justify-between rounded-xl border border-line bg-panel px-3 py-2 shadow-card">
      <span className="text-[13px] text-fg">Appearance</span>
      <div className="flex rounded-lg bg-subtle p-0.5" role="radiogroup" aria-label="Theme">
        {[
          ["light", Sun, "Light"],
          ["dark", Moon, "Dark"],
        ].map(([value, Icon, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={theme === value}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={cx(
              "grid h-6 w-8 place-items-center rounded-md transition-colors",
              theme === value ? "bg-elevated text-fg shadow-card" : "text-fg-faint hover:text-fg",
            )}
          >
            <Icon className="size-3.5" />
          </button>
        ))}
      </div>
    </div>
  );
}

function SidebarContent({ onClose, chat, health, stats, settings }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center justify-between px-4">
        <div className="flex items-center gap-2.5">
          <LogoMark size={26} />
          <span className="text-[15px] font-semibold tracking-tight text-fg">Nexora</span>
        </div>
        {onClose && (
          <IconButton label="Close sidebar" onClick={onClose} className="lg:hidden">
            <X className="size-4" />
          </IconButton>
        )}
      </div>

      <div className="px-3 pb-3">
        <Button onClick={chat.onNewChat} className="w-full justify-start" data-testid="new-chat-button">
          <Plus className="size-4" aria-hidden="true" />
          New chat
        </Button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-3 pt-2 pb-4">
        <SessionCard sessionId={chat.sessionId} startedAt={chat.sessionStartedAt} stats={stats} />
        <SystemStatus health={health} />
        <section>
          <SectionLabel>Settings</SectionLabel>
          <div className="space-y-2">
            <SystemPromptEditor
              defaultPrompt={health.data?.default_system_prompt}
              appliedPrompt={settings.systemPrompt}
              onApply={settings.onApplySystemPrompt}
            />
            {health.data?.failure_simulation_enabled && (
              <FailoverLab simulation={settings.simulation} onChange={settings.onSimulationChange} />
            )}
            <ThemeSwitch theme={settings.theme} setTheme={settings.setTheme} />
          </div>
        </section>
      </div>

      <div className="shrink-0 border-t border-line px-4 py-3 text-[11px] text-fg-faint">
        LiteLLM gateway · FastAPI · SQLite
      </div>
    </div>
  );
}

function useIsDesktop() {
  const query = "(min-width: 1024px)";
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = (e) => setMatches(e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return matches;
}

export function Sidebar({ mobileOpen, onMobileClose, ...props }) {
  const isDesktop = useIsDesktop();
  // Off-screen drawer content must not be reachable by Tab or screen readers.
  const hiddenOffCanvas = !isDesktop && !mobileOpen;

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e) => e.key === "Escape" && onMobileClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mobileOpen, onMobileClose]);

  // One instance only: static column on desktop, off-canvas drawer below lg.
  return (
    <>
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            className="fixed inset-0 z-30 bg-black/40 backdrop-blur-[2px] lg:hidden"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onMobileClose}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
      <aside
        aria-label="Sidebar"
        inert={hiddenOffCanvas}
        className={cx(
          "fixed inset-y-0 left-0 z-40 w-[86%] max-w-[300px] border-r border-line bg-canvas shadow-pop",
          "transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
          "lg:static lg:z-auto lg:w-[288px] lg:max-w-none lg:shrink-0 lg:translate-x-0 lg:shadow-none",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <SidebarContent {...props} onClose={onMobileClose} />
      </aside>
    </>
  );
}
