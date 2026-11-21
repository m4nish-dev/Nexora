import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth } from "../lib/api";

const POLL_MS = 30_000;

/** Polls GET /health. status: "checking" | "online" | "degraded" | "offline". */
export function useHealth() {
  const [state, setState] = useState({ status: "checking", data: null, latencyMs: null, detail: null, checkedAt: null });
  const inflight = useRef(null);

  const check = useCallback(async () => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    const started = performance.now();
    try {
      const data = await getHealth({ signal: controller.signal });
      setState({
        status: "online",
        data,
        latencyMs: Math.round(performance.now() - started),
        detail: null,
        checkedAt: new Date(),
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        status: error?.status === 503 ? "degraded" : "offline",
        data: prev.data,
        latencyMs: null,
        detail: error?.message ?? null,
        checkedAt: new Date(),
      }));
    }
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(check, POLL_MS);
    const onFocus = () => check();
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", onFocus);
      inflight.current?.abort();
    };
  }, [check]);

  return { ...state, refresh: check };
}
