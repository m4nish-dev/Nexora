import { useCallback, useEffect, useRef, useState } from "react";

const NEAR_BOTTOM_PX = 120;

/** Keeps the list pinned to the newest message unless the user has scrolled up to read. */
export function useAutoScroll(deps) {
  const containerRef = useRef(null);
  const pinnedRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  const onScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX;
    pinnedRef.current = near;
    setShowJump(!near);
  }, []);

  const scrollToBottom = useCallback((behavior = "smooth") => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    pinnedRef.current = true;
    setShowJump(false);
  }, []);

  useEffect(() => {
    if (pinnedRef.current) {
      requestAnimationFrame(() => scrollToBottom("smooth"));
    }
    // `deps` is supplied by the caller (message count, pending state): re-pin whenever they change.
  }, deps);

  return { containerRef, onScroll, showJump, scrollToBottom, pin: () => (pinnedRef.current = true) };
}
