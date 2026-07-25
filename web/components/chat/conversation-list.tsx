import Link from "next/link";
import { MessageSquareIcon } from "lucide-react";
import { formatRelativeTime } from "@/lib/format";
import type { ConversationSummary } from "@/lib/api/types";

/** Past conversations with one expert, listed on its chat page. */
export function ConversationList({
  conversations,
}: {
  conversations: ConversationSummary[];
}) {
  if (conversations.length === 0) return null;

  return (
    <div className="mx-auto w-full max-w-3xl">
      <h2 className="text-eyebrow mb-3 text-muted-foreground">Previous chats</h2>
      <ul className="flex flex-col">
        {conversations.map((conversation) => (
          <li key={conversation.id}>
            <Link
              href={`/chats/${conversation.id}`}
              className="flex items-center gap-2.5 rounded-lg px-2 py-2 text-sm hover:bg-muted"
            >
              <MessageSquareIcon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">
                {conversation.title ?? "Untitled chat"}
              </span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {formatRelativeTime(conversation.last_message_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
