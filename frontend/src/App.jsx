import { useCallback, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";
import { ArrowDown, Menu, Plus } from "lucide-react";
import { Sidebar } from "./components/Sidebar";
import { Composer } from "./components/Composer";
import { WelcomeScreen } from "./components/WelcomeScreen";
import { AssistantMessage, ErrorMessage, NoticeMessage, TypingIndicator, UserMessage } from "./components/Messages";
import { IconButton, LogoMark, StatusDot } from "./components/ui/primitives";
import { useChat } from "./hooks/useChat";
import { useHealth } from "./hooks/useHealth";
import { useTheme } from "./hooks/useTheme";
import { useAutoScroll } from "./hooks/useAutoScroll";
import { splitModel } from "./lib/format";

function TopBar({ title, onOpenSidebar, onNewChat, health, customPrompt }) {
  const model = health.data?.models?.[0];
  const tone = { online: "ok", degraded: "warn", offline: "danger", checking: "neutral" }[health.status];
  return (
    <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-canvas/80 px-3 backdrop-blur-md sm:px-5">
      <IconButton label="Open sidebar" onClick={onOpenSidebar} className="lg:hidden">
        <Menu className="size-4" />
      </IconButton>
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <LogoMark size={22} className="lg:hidden" />
        <h1 className="truncate text-sm font-medium text-fg" title={title}>
          {title}
        </h1>
        {customPrompt && (
          <span className="hidden shrink-0 rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] font-medium text-accent sm:inline">
            Custom prompt
          </span>
        )}
      </div>
      {model && (
        <span className="hidden items-center gap-2 rounded-lg border border-line bg-panel px-2.5 py-1 font-mono text-[11px] text-fg-muted shadow-card sm:inline-flex">
          <StatusDot tone={tone} />
          {splitModel(model).name}
        </span>
      )}
      <IconButton label="New chat" onClick={onNewChat} className="lg:hidden">
        <Plus className="size-4" />
      </IconButton>
    </header>
  );
}

export default function App() {
  const chat = useChat();
  const health = useHealth();
  const { theme, setTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [systemPrompt, setSystemPrompt] = useState(""); // "" = backend default
  const [simulation, setSimulation] = useState(null);
  const composerRef = useRef(null);

  const { items, pending } = chat;
  const { containerRef, onScroll, showJump, scrollToBottom, pin } = useAutoScroll([items.length, pending]);

  const stats = useMemo(() => {
    const replies = items.filter((i) => i.role === "assistant");
    return {
      turns: replies.length,
      cacheHits: replies.filter((i) => i.metadata?.resolution_source === "LLM_CACHE").length,
      failovers: replies.filter((i) => i.metadata?.fallback_attempts > 0).length,
    };
  }, [items]);

  const title = useMemo(() => {
    const first = items.find((i) => i.role === "user");
    return first ? first.content.slice(0, 80) : "New conversation";
  }, [items]);

  const send = useCallback(
    (text) => {
      pin();
      const sent = chat.send(text, {
        // Always send the effective prompt (custom, else the backend default). Omitting it would make
        // the backend keep a previously stored custom prompt, so "Reset" would silently not apply.
        systemPrompt: systemPrompt || health.data?.default_system_prompt || undefined,
        simulateFailure: simulation || undefined,
      });
      if (sent && simulation) setSimulation(null); // the hook applies to one request only
      return sent;
    },
    [chat, health.data?.default_system_prompt, pin, simulation, systemPrompt],
  );

  const newChat = useCallback(() => {
    chat.newChat();
    setSimulation(null);
    setSidebarOpen(false);
    requestAnimationFrame(() => composerRef.current?.focus());
  }, [chat]);

  const applySystemPrompt = useCallback(
    (prompt) => {
      setSystemPrompt(prompt);
      if (items.length > 0) chat.addNotice(prompt ? "Custom system prompt applied" : "System prompt reset to default");
    },
    [chat, items.length],
  );

  const pendingLabel = simulation ? "Routing through the key pool" : "Thinking";

  return (
    <MotionConfig reducedMotion="user">
      <div className="flex h-dvh overflow-hidden bg-canvas">
        <Sidebar
          mobileOpen={sidebarOpen}
          onMobileClose={() => setSidebarOpen(false)}
          chat={{ sessionId: chat.sessionId, sessionStartedAt: chat.sessionStartedAt, onNewChat: newChat }}
          health={health}
          stats={stats}
          settings={{
            systemPrompt,
            onApplySystemPrompt: applySystemPrompt,
            simulation,
            onSimulationChange: setSimulation,
            theme,
            setTheme,
          }}
        />

        <main className="relative flex min-w-0 flex-1 flex-col">
          <TopBar
            title={title}
            onOpenSidebar={() => setSidebarOpen(true)}
            onNewChat={newChat}
            health={health}
            customPrompt={Boolean(systemPrompt)}
          />

          <div
            ref={containerRef}
            onScroll={onScroll}
            className="flex flex-1 flex-col overflow-y-auto"
            data-testid="message-list"
          >
            {items.length === 0 ? (
              <WelcomeScreen onPick={send} disabled={pending} />
            ) : (
              <div className="mx-auto w-full max-w-3xl flex-1 space-y-7 px-4 pt-8 pb-6 sm:px-6" aria-live="polite">
                {items.map((item) => {
                  switch (item.role) {
                    case "user":
                      return <UserMessage key={item.id} item={item} />;
                    case "assistant":
                      return <AssistantMessage key={item.id} item={item} />;
                    case "error":
                      return <ErrorMessage key={item.id} item={item} onRetry={chat.retry} retryDisabled={pending} />;
                    default:
                      return <NoticeMessage key={item.id} item={item} />;
                  }
                })}
                {pending && <TypingIndicator label={pendingLabel} />}
              </div>
            )}

            <Composer
              ref={composerRef}
              onSend={send}
              pending={pending}
              simulation={simulation}
              onClearSimulation={() => setSimulation(null)}
            />
          </div>

          <AnimatePresence>
            {showJump && items.length > 0 && (
              <motion.button
                type="button"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                onClick={() => scrollToBottom()}
                className="absolute bottom-36 left-1/2 z-20 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-elevated px-3 py-1.5 text-xs text-fg-muted shadow-pop hover:text-fg"
              >
                <ArrowDown className="size-3.5" />
                Latest
              </motion.button>
            )}
          </AnimatePresence>
        </main>
      </div>
    </MotionConfig>
  );
}
