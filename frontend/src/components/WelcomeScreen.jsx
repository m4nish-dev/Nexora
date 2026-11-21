import { motion } from "framer-motion";
import { Brain, Database, GitCompareArrows, PenLine } from "lucide-react";
import { LogoMark } from "./ui/primitives";

const SUGGESTIONS = [
  {
    icon: Database,
    title: "Explain a concept",
    prompt: "How does response caching reduce the cost and latency of LLM apps?",
  },
  {
    icon: GitCompareArrows,
    title: "Compare trade-offs",
    prompt: "SQLite vs Postgres for a small chat app — what are the trade-offs?",
  },
  {
    icon: PenLine,
    title: "Draft something",
    prompt: "Write a crisp three-sentence release note for automatic API key failover.",
  },
  {
    icon: Brain,
    title: "Test memory",
    prompt: "My name is Ada and I love astronomy. Remember that, then suggest a weekend project for me.",
  },
];

export function WelcomeScreen({ onPick, disabled }) {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center px-4 py-10 sm:px-6">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      >
        <LogoMark size={40} className="mb-6" />
        <h1 className="text-2xl font-semibold tracking-tight text-fg sm:text-[28px]">How can I help today?</h1>
        <p className="mt-2 max-w-xl text-[15px] leading-7 text-fg-muted">
          Ask anything. Every reply shows whether it came from{" "}
          <span className="font-medium text-accent">live inference</span> or the{" "}
          <span className="font-medium text-cache">response cache</span>, with its model, latency and token usage.
        </p>
      </motion.div>

      <div className="mt-8 grid gap-2.5 sm:grid-cols-2">
        {SUGGESTIONS.map(({ icon: Icon, title, prompt }, i) => (
          <motion.button
            key={title}
            type="button"
            disabled={disabled}
            onClick={() => onPick(prompt)}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.06 + i * 0.04, ease: [0.25, 0.1, 0.25, 1] }}
            className="group flex items-start gap-3 rounded-xl border border-line bg-panel p-3.5 text-left shadow-card transition-colors duration-150 hover:border-line-strong hover:bg-elevated disabled:opacity-50"
          >
            <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-line bg-subtle text-fg-muted transition-colors group-hover:text-accent">
              <Icon className="size-4" aria-hidden="true" />
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-fg">{title}</span>
              <span className="mt-0.5 block text-[13px] leading-5 text-fg-muted">{prompt}</span>
            </span>
          </motion.button>
        ))}
      </div>
    </div>
  );
}
