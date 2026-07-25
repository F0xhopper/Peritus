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
}: {
  messages: ChatMessage[];
  pending: PendingAnswer | null;
  statusLine: string | null;
  streaming: boolean;
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

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className="flex-1 overflow-y-auto"
    >
      <div
        className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-1 py-4"
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
              hasContradiction={message.has_contradiction}
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
            hasContradiction={pending.has_contradiction}
            interrupted={pending.interrupted}
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
