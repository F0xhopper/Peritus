"use client";

import * as React from "react";
import { Message } from "@/components/chat/message";
import { StatusLine } from "@/components/chat/status-line";
import type { PendingAnswer } from "@/components/chat/use-chat-stream";
import type { ChatMessage } from "@/lib/api/types";

// Mirrors CHAT_HISTORY_MAX_MESSAGES in api/src/peritus/core/config.py. Only
// used to be honest about what the model can still see; the whole transcript
// renders regardless.
const HISTORY_WINDOW = 20;

export function MessageList({
  messages,
  pending,
  statusLine,
  streaming,
  emptyState,
}: {
  messages: ChatMessage[];
  pending: PendingAnswer | null;
  statusLine: string | null;
  streaming: boolean;
  /** Shown while the transcript is empty. Restarting a chat lands here every
   * time, so "no messages yet" is a normal state rather than an edge case, and
   * an unexplained pane of black above the composer is not an answer to it. */
  emptyState?: React.ReactNode;
}) {
  const bottomRef = React.useRef<HTMLDivElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  // Only auto-scroll when the user is already at the bottom — yanking the view
  // away from something they scrolled up to read is worse than a stale view.
  const stickToBottom = React.useRef(true);

  const handleScroll = React.useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    stickToBottom.current = distance < 80;
  }, []);

  React.useEffect(() => {
    if (stickToBottom.current) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, pending?.content, statusLine]);

  // Index of the first message the model still sees, so older turns can be
  // marked as out of its window.
  const cutoff = Math.max(0, messages.length - HISTORY_WINDOW);

  if (emptyState && messages.length === 0 && !pending && !statusLine) {
    return (
      <div className="flex flex-1 items-center justify-center overflow-y-auto p-4">
        {emptyState}
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      // Feathered top and bottom. Without the mask, a scrolled transcript is
      // sliced clean through a line of type at both ends — the answer appears
      // to start and stop mid-word against the header rule and the composer,
      // which reads as clipping rather than as more text above and below. The
      // mask only bites once there is something to scroll, so a short answer
      // is never dimmed at its own first line.
      className="flex-1 overflow-y-auto [mask-image:linear-gradient(to_bottom,transparent,black_1.25rem,black_calc(100%-1.25rem),transparent)]"
    >
      <div
        className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-1 py-5"
        aria-live="polite"
        aria-busy={streaming}
      >
        {messages.map((message, index) => (
          <React.Fragment key={message.id}>
            {index === cutoff && cutoff > 0 && (
              <div className="flex items-center gap-2 py-1">
                <div className="h-px flex-1 bg-border" />
                <span className="text-[0.7rem] text-muted-foreground">
                  older messages aren&apos;t visible to the expert
                </span>
                <div className="h-px flex-1 bg-border" />
              </div>
            )}
            <Message
              role={message.role}
              content={message.content}
              citations={message.citations}
              interrupted={message.interrupted}
              messageKey={String(message.id)}
            />
          </React.Fragment>
        ))}

        {pending && pending.content && (
          <Message
            role="assistant"
            content={pending.content}
            citations={pending.citations}
            interrupted={pending.interrupted}
            trail={pending.trail}
            messageKey="pending"
            streaming={streaming}
          />
        )}

        {statusLine && <StatusLine message={statusLine} />}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
