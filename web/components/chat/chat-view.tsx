"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircleIcon, ChevronLeftIcon, RotateCcwIcon } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Composer } from "@/components/chat/composer";
import { ConversationMenu } from "@/components/chat/conversation-menu";
import { MessageList } from "@/components/chat/message-list";
import { useChatStream } from "@/components/chat/use-chat-stream";
import type { ConversationDetail } from "@/lib/api/types";

/** sessionStorage key carrying the first question across the
 * /experts/[slug]/chat → /chats/[id] navigation. Survives the redirect, dies
 * with the tab — see the composer handoff in app/(dashboard)/experts/[slug]/chat. */
export const PENDING_QUESTION_KEY = "peritus:pending-question";

export function ChatView({ conversation }: { conversation: ConversationDetail }) {
  const router = useRouter();
  const [title, setTitle] = React.useState(conversation.title);

  // The `meta` event and the rename dialog set the title optimistically; when
  // the server's version arrives it takes over again. Adjusting during render
  // (rather than in an effect) is React's documented way to reset state on a
  // prop change — no extra pass, no flash of the stale title.
  const [serverTitle, setServerTitle] = React.useState(conversation.title);
  if (serverTitle !== conversation.title) {
    setServerTitle(conversation.title);
    setTitle(conversation.title);
  }

  const handleFirstMessage = React.useCallback((next: string | null) => {
    if (next) setTitle(next);
  }, []);

  // Pull the persisted transcript back in once the answer is stored, which
  // also refreshes the sidebar recents (title, ordering).
  const handleComplete = React.useCallback(() => {
    router.refresh();
  }, [router]);

  const { messages, pending, status, statusLine, error, send, stop, retryable } =
    useChatStream({
      conversationId: conversation.id,
      initialMessages: conversation.messages,
      onFirstMessage: handleFirstMessage,
      onComplete: handleComplete,
    });

  // A question handed over from the new-chat composer auto-sends on arrival,
  // so the user's first message isn't lost to the redirect. The key is cleared
  // before sending so a refresh can't replay it, and the ref guards against a
  // second send if this effect re-runs.
  const handedOff = React.useRef(false);
  React.useEffect(() => {
    if (handedOff.current) return;
    const handoff = sessionStorage.getItem(PENDING_QUESTION_KEY);
    if (!handoff) return;
    sessionStorage.removeItem(PENDING_QUESTION_KEY);
    handedOff.current = true;

    try {
      const { conversationId, question } = JSON.parse(handoff) as {
        conversationId: string;
        question: string;
      };
      if (conversationId === conversation.id && question) {
        void send(question);
      }
    } catch {
      // Malformed handoff (hand-edited storage) — nothing to send.
    }
  }, [conversation.id, send]);

  const expertLabel =
    conversation.expert_persona_name ?? conversation.expert_topic;
  const streaming = status === "streaming";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border/60 pb-3">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Back to expert"
          nativeButton={false}
          render={<Link href={`/experts/${conversation.expert_slug}/chat`} />}
        >
          <ChevronLeftIcon />
        </Button>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-sm font-medium">
            {title ?? "New chat"}
          </h1>
          <Link
            href={`/experts/${conversation.expert_slug}`}
            className="truncate text-xs text-muted-foreground hover:text-foreground hover:underline"
          >
            {expertLabel}
          </Link>
        </div>
        <ConversationMenu
          conversationId={conversation.id}
          title={title}
          expertSlug={conversation.expert_slug}
          onRenamed={setTitle}
        />
      </div>

      <MessageList
        messages={messages}
        pending={pending}
        statusLine={statusLine}
        streaming={streaming}
      />

      {error && (
        <div className="mx-auto w-full max-w-3xl pb-2">
          <div className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
            <AlertCircleIcon className="mt-0.5 size-4 shrink-0" />
            <p className="flex-1">{error}</p>
            {retryable && (
              <Button
                size="xs"
                variant="outline"
                onClick={() => void send(retryable)}
              >
                <RotateCcwIcon />
                Retry
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="border-t border-border/60 pt-3">
        <Composer
          onSend={(question) => {
            if (conversation.expert_status !== "ready") {
              toast.error("This expert is rebuilding — try again once it's ready.");
              return;
            }
            void send(question);
          }}
          onStop={stop}
          streaming={streaming}
          autoFocus
        />
      </div>
    </div>
  );
}
