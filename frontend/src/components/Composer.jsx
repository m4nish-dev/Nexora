import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowUp, FlaskConical, X } from "lucide-react";
import { cx, Kbd } from "./ui/primitives";

const MAX_CHARS = 4000;
const MAX_HEIGHT_PX = 220;

export const Composer = forwardRef(function Composer({ onSend, pending, simulation, onClearSimulation }, ref) {
  const [value, setValue] = useState("");
  const textareaRef = useRef(null);

  useImperativeHandle(ref, () => ({ focus: () => textareaRef.current?.focus() }), []);

  const resize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, []);

  useEffect(resize, [value, resize]);

  const length = value.trim().length;
  const canSend = length > 0 && !pending;

  const submit = () => {
    if (!canSend) return;
    if (onSend(value)) setValue("");
  };

  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="pointer-events-none sticky bottom-0 z-10 bg-gradient-to-t from-canvas from-60% to-transparent px-3 pt-6 pb-[max(env(safe-area-inset-bottom),12px)] sm:px-6 sm:pb-5">
      <div className="pointer-events-auto mx-auto w-full max-w-3xl">
        <AnimatePresence>
          {simulation && (
            <motion.div
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6 }}
              transition={{ duration: 0.18 }}
              className="mb-2 flex items-center gap-2 rounded-lg border border-warn/25 bg-warn-soft px-3 py-1.5 text-xs text-warn"
            >
              <FlaskConical className="size-3.5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">
                Next message sends <span className="font-mono">X-Simulate-Failure: {simulation}</span>
              </span>
              <button
                type="button"
                onClick={onClearSimulation}
                className="rounded p-0.5 hover:bg-warn/15"
                aria-label="Cancel failure simulation"
              >
                <X className="size-3.5" />
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className={cx(
            "rounded-2xl border bg-elevated shadow-composer transition-colors duration-150",
            "border-line focus-within:border-line-strong",
          )}
        >
          <label htmlFor="chat-input" className="sr-only">
            Message Nexora
          </label>
          <textarea
            id="chat-input"
            ref={textareaRef}
            data-testid="chat-input"
            rows={1}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message Nexora…"
            autoComplete="off"
            className="block max-h-[220px] min-h-[52px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-6 text-fg outline-none placeholder:text-fg-faint focus-visible:outline-none"
          />
          <div className="flex items-center justify-between gap-3 px-3 pb-3">
            <p className="hidden items-center gap-1.5 pl-1 text-xs text-fg-faint sm:flex">
              <Kbd>Enter</Kbd> to send <span className="text-line-strong">·</span> <Kbd>Shift</Kbd>
              <Kbd>Enter</Kbd> new line
            </p>
            <div className="ml-auto flex items-center gap-3">
              {length > MAX_CHARS * 0.85 && (
                <span
                  className={cx("font-mono text-xs tabular-nums", length > MAX_CHARS ? "text-danger" : "text-fg-faint")}
                  aria-live="polite"
                >
                  {length}/{MAX_CHARS}
                </span>
              )}
              <button
                type="submit"
                data-testid="send-button"
                disabled={!canSend}
                aria-label="Send message"
                className={cx(
                  "inline-grid size-8 place-items-center rounded-lg transition-all duration-150",
                  canSend
                    ? "bg-accent text-accent-fg shadow-card hover:bg-accent-hover active:scale-95"
                    : "bg-subtle text-fg-faint",
                )}
              >
                <ArrowUp className="size-4" strokeWidth={2.4} />
              </button>
            </div>
          </div>
        </form>
        <p className="mt-2 text-center text-[11px] text-fg-faint">
          Responses can be inaccurate. Metadata below each reply is reported by the server for that request.
        </p>
      </div>
    </div>
  );
});
