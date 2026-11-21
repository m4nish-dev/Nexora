import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

const cx = (...classes) => classes.filter(Boolean).join(" ");
export { cx };

export function LogoMark({ size = 28, className = "" }) {
  return (
    <span
      className={cx("inline-grid shrink-0 place-items-center rounded-[28%] bg-accent text-accent-fg shadow-card", className)}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" width={size * 0.58} height={size * 0.58} fill="none">
        <path d="M6.5 17.5v-11l11 11v-11" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

const buttonVariants = {
  primary: "bg-accent text-accent-fg hover:bg-accent-hover shadow-card",
  secondary: "border border-line bg-elevated text-fg hover:bg-subtle hover:border-line-strong shadow-card",
  ghost: "text-fg-muted hover:text-fg hover:bg-subtle",
};

export function Button({ variant = "secondary", size = "md", className = "", children, ...props }) {
  const sizes = { sm: "h-7 px-2.5 text-xs gap-1.5", md: "h-9 px-3 text-sm gap-2" };
  return (
    <button
      type="button"
      className={cx(
        "inline-flex items-center justify-center rounded-lg font-medium transition-colors duration-150",
        "disabled:pointer-events-none disabled:opacity-45",
        sizes[size],
        buttonVariants[variant],
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function IconButton({ label, className = "", children, ...props }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "inline-grid size-8 place-items-center rounded-lg text-fg-muted transition-colors duration-150",
        "hover:bg-subtle hover:text-fg disabled:pointer-events-none disabled:opacity-40",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Kbd({ children }) {
  return (
    <kbd className="inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-line bg-subtle px-1 font-mono text-[10px] font-medium text-fg-muted">
      {children}
    </kbd>
  );
}

export function StatusDot({ tone = "neutral", pulse = false }) {
  const tones = {
    ok: "bg-cache",
    warn: "bg-warn",
    danger: "bg-danger",
    neutral: "bg-fg-faint",
  };
  return (
    <span className="relative inline-flex size-2 shrink-0">
      {pulse && <span className={cx("absolute inset-0 animate-ping rounded-full opacity-50", tones[tone])} />}
      <span className={cx("relative inline-flex size-2 rounded-full", tones[tone])} />
    </span>
  );
}

export function SectionLabel({ children, action }) {
  return (
    <div className="mb-2 flex items-center justify-between px-1">
      <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-fg-faint">{children}</h2>
      {action}
    </div>
  );
}

async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for non-secure contexts.
    const el = document.createElement("textarea");
    el.value = text;
    el.setAttribute("readonly", "");
    el.style.position = "fixed";
    el.style.opacity = "0";
    document.body.appendChild(el);
    el.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(el);
    return ok;
  }
}

export function useCopy(timeout = 1500) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => clearTimeout(timer.current), []);
  const copy = useCallback(
    async (text) => {
      if (await writeClipboard(text)) {
        setCopied(true);
        clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), timeout);
      }
    },
    [timeout],
  );
  return { copied, copy };
}

export function CopyButton({ text, label = "Copy", className = "" }) {
  const { copied, copy } = useCopy();
  return (
    <IconButton label={copied ? "Copied" : label} onClick={() => copy(text)} className={cx("size-7", className)}>
      {copied ? <Check className="size-3.5 text-cache" /> : <Copy className="size-3.5" />}
    </IconButton>
  );
}
