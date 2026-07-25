import { notFound } from "next/navigation";
import { ChatView } from "@/components/chat/chat-view";
import { getConversation } from "@/lib/api/data";

export default async function ChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const conversation = await getConversation(id);

  // 404 covers "no such chat" and "not yours" alike — the API hides the
  // difference deliberately, and so does this page.
  if (!conversation) {
    notFound();
  }

  return <ChatView conversation={conversation} />;
}
