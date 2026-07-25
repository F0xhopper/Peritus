"use client";

import * as React from "react";
import { streamChat, ChatStreamError } from "@/lib/api/sse";
import type { ChatMessage, Citation } from "@/lib/api/types";

// Owns the live half of a conversation: the optimistic user bubble, the answer
// accumulating token by token, and the terminal states.
//
// The persisted transcript arrives as `initialMessages` from a server
// component. Its identity only changes when the server payload does (client
// re-renders reuse the same props object), so that is the signal to drop local
// optimistic state and let the authoritative version take over.

export type ChatStatus = "idle" | "streaming" | "error";

/** The answer streaming right now. It has no id — the server assigns one only
 * once the message is persisted, which is after the stream ends. */
export interface PendingAnswer {
  content: string;
  citations: Citation[] | null;
  has_contradiction: boolean;
  interrupted: boolean;
}

export interface ChatStreamState {
  messages: ChatMessage[];
  pending: PendingAnswer | null;
  status: ChatStatus;
  statusLine: string | null;
  error: string | null;
  send: (question: string) => Promise<void>;
  stop: () => void;
  /** Question to re-send when the last turn failed before any answer arrived. */
  retryable: string | null;
}

// Local-only ids for optimistic bubbles. Negative so they can never collide
// with a server BIGSERIAL id once a refresh brings the real rows in.
let optimisticId = -1;

export function useChatStream({
  conversationId,
  initialMessages,
  onFirstMessage,
  onComplete,
}: {
  conversationId: string;
  initialMessages: ChatMessage[];
  /** Fired with the server-assigned title after the first message, so the page
   * can update its heading and the sidebar without a second fetch. */
  onFirstMessage?: (title: string | null) => void;
  /** Fired when a stream settles — the caller refreshes the server data. */
  onComplete?: () => void;
}): ChatStreamState {
  const [serverMessages, setServerMessages] = React.useState(initialMessages);
  const [localMessages, setLocalMessages] = React.useState<ChatMessage[]>([]);
  const [pending, setPending] = React.useState<PendingAnswer | null>(null);
  const [status, setStatus] = React.useState<ChatStatus>("idle");
  const [statusLine, setStatusLine] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [retryable, setRetryable] = React.useState<string | null>(null);

  const abortRef = React.useRef<AbortController | null>(null);
  const streamingRef = React.useRef(false);
  const mountedRef = React.useRef(true);

  // Fresh server data supersedes the optimistic copies it now contains. Held
  // back while a stream is in flight so an unrelated refresh can't blank the
  // answer being written.
  React.useEffect(() => {
    if (streamingRef.current) return;
    setServerMessages(initialMessages);
    setLocalMessages([]);
    setPending(null);
  }, [initialMessages]);

  // Deliberately NOT aborting the stream on unmount. Strict Mode tears every
  // component down once on mount, which would kill a first message sent from
  // the mount effect (the composer handoff) before its request body finished
  // uploading. Letting an orphaned stream run to completion is also the better
  // outcome: the server persists the whole answer, so navigating away and back
  // shows a complete reply instead of a truncated one. Only the Stop button
  // (and closing the tab) cuts a stream short.
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const messages = React.useMemo(
    () => [...serverMessages, ...localMessages],
    [serverMessages, localMessages],
  );
  // Kept in a ref so `send` can inspect the transcript without taking it as a
  // dependency (which would rebuild the callback on every token).
  const messagesRef = React.useRef(messages);
  React.useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const send = React.useCallback(
    async (question: string) => {
      const trimmed = question.trim();
      if (!trimmed || streamingRef.current) return;

      streamingRef.current = true;
      const controller = new AbortController();
      abortRef.current = controller;

      setError(null);
      setRetryable(null);
      setStatus("streaming");
      setStatusLine(null);
      setPending({
        content: "",
        citations: null,
        has_contradiction: false,
        interrupted: false,
      });

      // Optimistic user bubble — skipped when retrying a question already at
      // the end of the transcript (its stream died before producing tokens, so
      // the server reuses that row rather than inserting a duplicate).
      const last = messagesRef.current[messagesRef.current.length - 1];
      const isRetryOfOrphan = last?.role === "user" && last.content === trimmed;
      const optimistic: ChatMessage | null = isRetryOfOrphan
        ? null
        : {
            id: optimisticId--,
            role: "user",
            content: trimmed,
            citations: null,
            has_contradiction: false,
            interrupted: false,
            created_at: new Date().toISOString(),
          };
      if (optimistic) setLocalMessages((prev) => [...prev, optimistic]);

      let sawToken = false;

      try {
        const events = streamChat(
          `/api/conversations/${conversationId}/messages`,
          { question: trimmed },
          controller.signal,
        );

        for await (const event of events) {
          switch (event.type) {
            case "meta":
              onFirstMessage?.(event.title);
              break;
            case "status":
              setStatusLine(event.message);
              break;
            case "token":
              sawToken = true;
              setStatusLine(null);
              setPending((p) => (p ? { ...p, content: p.content + event.text } : p));
              break;
            case "sources":
              setPending((p) =>
                p
                  ? {
                      ...p,
                      citations: event.citations,
                      has_contradiction: event.has_contradiction,
                    }
                  : p,
              );
              break;
            case "done":
              setStatus("idle");
              setStatusLine(null);
              break;
            case "error":
              setStatus("error");
              setError(event.message);
              setStatusLine(null);
              if (!sawToken) setRetryable(trimmed);
              break;
          }
        }
      } catch (err) {
        setStatusLine(null);
        if (controller.signal.aborted) {
          setStatus("idle");
          if (sawToken) {
            // Stop pressed mid-answer: the server persists what streamed as
            // interrupted, so mark the local bubble to match.
            setPending((p) => (p ? { ...p, interrupted: true } : p));
          } else {
            // Stopped before a single token — there is no answer to show and
            // the server stored none. Offer the question back rather than
            // letting the turn vanish with no explanation.
            setPending(null);
            setRetryable(trimmed);
          }
        } else if (err instanceof ChatStreamError) {
          setStatus("error");
          setError(
            err.status === 409
              ? "This chat is already answering in another window."
              : err.message,
          );
          setPending(null);
          if (err.status === 409 && optimistic) {
            // The question was never accepted, so the optimistic bubble is a
            // lie — drop it rather than leave a turn that does not exist.
            setLocalMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
          } else if (!sawToken) {
            setRetryable(trimmed);
          }
        } else {
          setStatus("error");
          setError("The connection dropped before the answer finished.");
          if (!sawToken) setRetryable(trimmed);
        }
      } finally {
        streamingRef.current = false;
        abortRef.current = null;
        // A stream that outlived its page still finishes and persists, but it
        // must not refresh whatever route the user moved on to.
        if (mountedRef.current) onComplete?.();
      }
    },
    [conversationId, onFirstMessage, onComplete],
  );

  const stop = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, pending, status, statusLine, error, send, stop, retryable };
}
