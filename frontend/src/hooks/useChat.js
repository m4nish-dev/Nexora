import { useCallback, useEffect, useRef, useState } from "react";
import { sendChat } from "../lib/api";
import { createSessionId } from "../lib/session";

let nextId = 0;
const uid = (prefix) => `${prefix}-${Date.now().toString(36)}-${(nextId++).toString(36)}`;

/**
 * Conversation state for the active session.
 *
 * The backend owns history (SQLite); the client only sends the newest message. Items:
 *   { id, role: "user" | "assistant" | "error" | "notice", content, metadata?, error?, request?, createdAt }
 */
export function useChat() {
  const [sessionId, setSessionId] = useState(createSessionId);
  const [sessionStartedAt, setSessionStartedAt] = useState(() => new Date());
  const [items, setItems] = useState([]);
  const [pending, setPending] = useState(false);

  const pendingRef = useRef(false); // synchronous guard against double submits (Enter + click)
  const abortRef = useRef(null);
  const sessionRef = useRef(sessionId);
  const itemsRef = useRef(items);
  sessionRef.current = sessionId;
  itemsRef.current = items;

  useEffect(() => () => abortRef.current?.abort(), []);

  const runRequest = useCallback(async (request) => {
    const controller = new AbortController();
    abortRef.current = controller;
    const requestSession = sessionRef.current;
    pendingRef.current = true;
    setPending(true);
    try {
      const data = await sendChat({ sessionId: requestSession, ...request, signal: controller.signal });
      if (sessionRef.current !== requestSession) return; // user started a new chat meanwhile
      setItems((prev) => [
        ...prev,
        { id: uid("a"), role: "assistant", content: data.reply, metadata: data.metadata, createdAt: new Date() },
      ]);
    } catch (error) {
      if (sessionRef.current !== requestSession) return; // stale (aborted by "New chat")
      setItems((prev) => [
        ...prev,
        {
          id: uid("e"),
          role: "error",
          content: error?.message || "Something went wrong.",
          error: { kind: error?.kind ?? "unknown", status: error?.status ?? 0 },
          request,
          createdAt: new Date(),
        },
      ]);
    } finally {
      // Only the request that is still current may clear the busy state ("New chat" resets it itself).
      if (abortRef.current === controller) {
        abortRef.current = null;
        pendingRef.current = false;
        setPending(false);
      }
    }
  }, []);

  /** Returns false if the message was not sent (empty or a request is already in flight). */
  const send = useCallback(
    (text, { systemPrompt, simulateFailure } = {}) => {
      if (pendingRef.current) return false;
      const message = text.trim();
      if (!message) return false;
      setItems((prev) => [...prev, { id: uid("u"), role: "user", content: message, createdAt: new Date() }]);
      runRequest({ message, systemPrompt, simulateFailure });
      return true;
    },
    [runRequest],
  );

  /** Re-send the request behind a failed turn without duplicating the user bubble. */
  const retry = useCallback(
    (errorId) => {
      if (pendingRef.current) return;
      const target = itemsRef.current.find((item) => item.id === errorId);
      if (!target?.request) return;
      setItems((prev) => prev.filter((item) => item.id !== errorId));
      // A failover simulation applies to one attempt only; the retry goes through normally.
      runRequest({ ...target.request, simulateFailure: undefined });
    },
    [runRequest],
  );

  const addNotice = useCallback((content) => {
    setItems((prev) => [...prev, { id: uid("n"), role: "notice", content, createdAt: new Date() }]);
  }, []);

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    pendingRef.current = false;
    setPending(false);
    setItems([]);
    setSessionId(createSessionId());
    setSessionStartedAt(new Date());
  }, []);

  return { sessionId, sessionStartedAt, items, pending, send, retry, newChat, addNotice };
}
