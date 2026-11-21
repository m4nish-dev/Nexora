import { memo } from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, RotateCcw, Settings2, WifiOff } from "lucide-react";
import { Button, CopyButton, LogoMark } from "./ui/primitives";
import { MetaBar } from "./MetaBar";
import { formatTime } from "../lib/format";

const enter = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.22, ease: [0.25, 0.1, 0.25, 1] },
};

const markdownComponents = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

const Markdown = memo(function Markdown({ text }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

export function UserMessage({ item }) {
  return (
    <motion.div {...enter} className="flex justify-end" data-testid="user-message">
      <div className="max-w-[85%] rounded-2xl rounded-br-md border border-line bg-elevated px-4 py-2.5 text-[15px] leading-7 whitespace-pre-wrap text-fg shadow-card [overflow-wrap:anywhere] sm:max-w-[75%]">
        {item.content}
      </div>
    </motion.div>
  );
}

function AssistantShell({ children, time }) {
  return (
    <div className="group flex gap-3 sm:gap-4">
      <LogoMark size={28} className="mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex h-7 items-center gap-2 text-[13px]">
          <span className="font-medium text-fg">Nexora</span>
          {time && <span className="text-fg-faint">{formatTime(time)}</span>}
        </div>
        {children}
      </div>
    </div>
  );
}

export const AssistantMessage = memo(function AssistantMessage({ item }) {
  return (
    <motion.div {...enter} data-testid="assistant-message">
      <AssistantShell time={item.createdAt}>
        <Markdown text={item.content} />
        <div className="mt-3 flex items-start justify-between gap-2">
          <MetaBar metadata={item.metadata} />
          <CopyButton
            text={item.content}
            label="Copy reply"
            className="opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
          />
        </div>
      </AssistantShell>
    </motion.div>
  );
});

const errorCopy = {
  unavailable: { title: "All providers unavailable", icon: AlertTriangle },
  validation: { title: "Request rejected", icon: AlertTriangle },
  network: { title: "Connection problem", icon: WifiOff },
  timeout: { title: "Request timed out", icon: WifiOff },
  server: { title: "Something went wrong", icon: AlertTriangle },
  unknown: { title: "Something went wrong", icon: AlertTriangle },
};

export function ErrorMessage({ item, onRetry, retryDisabled }) {
  const { title, icon: Icon } = errorCopy[item.error?.kind] ?? errorCopy.unknown;
  const canRetry = item.error?.kind !== "validation";
  return (
    <motion.div {...enter} role="alert" data-testid="error-message">
      <AssistantShell time={item.createdAt}>
        <div className="rounded-xl border border-danger/25 bg-danger-soft px-4 py-3">
          <div className="flex items-start gap-3">
            <Icon className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-fg">
                {title}
                {item.error?.status ? (
                  <span className="rounded border border-danger/25 px-1.5 font-mono text-[11px] font-normal text-danger">
                    HTTP {item.error.status}
                  </span>
                ) : null}
              </p>
              <p className="mt-1 text-sm leading-6 text-fg-muted">{item.content}</p>
              {item.request?.simulateFailure && (
                <p className="mt-1 font-mono text-xs text-fg-faint">X-Simulate-Failure: {item.request.simulateFailure}</p>
              )}
            </div>
            {canRetry && (
              <Button size="sm" onClick={() => onRetry(item.id)} disabled={retryDisabled} className="shrink-0">
                <RotateCcw className="size-3.5" aria-hidden="true" />
                Retry
              </Button>
            )}
          </div>
        </div>
      </AssistantShell>
    </motion.div>
  );
}

export function NoticeMessage({ item }) {
  return (
    <motion.div {...enter} className="flex items-center gap-3 py-1 text-xs text-fg-faint" role="status">
      <span className="h-px flex-1 bg-line" />
      <span className="inline-flex items-center gap-1.5">
        <Settings2 className="size-3.5" aria-hidden="true" />
        {item.content}
      </span>
      <span className="h-px flex-1 bg-line" />
    </motion.div>
  );
}

export function TypingIndicator({ label = "Thinking" }) {
  return (
    <motion.div {...enter} aria-live="polite" data-testid="typing-indicator">
      <AssistantShell>
        <div className="flex h-7 items-center gap-2.5 text-sm text-fg-muted">
          <span className="flex gap-1" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <motion.span
                key={i}
                className="size-1.5 rounded-full bg-fg-faint"
                animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
                transition={{ duration: 1, repeat: Infinity, delay: i * 0.15, ease: "easeInOut" }}
              />
            ))}
          </span>
          <span>{label}…</span>
        </div>
      </AssistantShell>
    </motion.div>
  );
}
