"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Composer } from "@/components/chat/composer";
import { PENDING_QUESTION_KEY } from "@/components/chat/chat-view";

// First-message flow, chosen to avoid empty-conversation litter: the draft
// lives here until submit, then POST creates the conversation and we navigate
// to it with the question handed over in sessionStorage (survives the
// navigation, dies with the tab). One extra round-trip, no half-created state
// sitting in a URL.

export function NewChatComposer({
  slug,
  ready,
}: {
  slug: string;
  ready: boolean;
}) {
  const router = useRouter();
  const [creating, setCreating] = React.useState(false);

  const start = async (question: string) => {
    if (creating) return;
    setCreating(true);
    try {
      const res = await fetch(`/api/experts/${slug}/conversations`, {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error((await res.json()).error ?? res.statusText);
      }
      const conversation = (await res.json()) as { id: string };
      sessionStorage.setItem(
        PENDING_QUESTION_KEY,
        JSON.stringify({ conversationId: conversation.id, question }),
      );
      // push, not replace: back from the new chat should return to this
      // composer, not skip past it to whatever page came before it.
      router.push(`/chats/${conversation.id}`);
    } catch (err) {
      setCreating(false);
      toast.error(
        err instanceof Error ? err.message : "Could not start the chat.",
      );
    }
  };

  return (
    <Composer
      onSend={(question) => void start(question)}
      streaming={false}
      disabled={!ready || creating}
      placeholder={
        ready ? "Ask the expert…" : "Available when the expert is ready"
      }
      autoFocus={ready}
    />
  );
}
