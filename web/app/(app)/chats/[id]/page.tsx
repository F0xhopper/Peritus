import { ChatView } from '@/components/chat/chat-view'
import { getConversation, getExpert, getExpertConversations } from '@/lib/api/data'

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const conversation = await getConversation(id)
  return { title: conversation.title ?? 'Chat' }
}

export default async function ChatPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const conversation = await getConversation(id)
  // The conversation carries `expert_slug`, so the expert is one extra fetch
  // rather than a lookup through the whole list.
  const [expert, siblings] = await Promise.all([
    getExpert(conversation.expert_slug),
    getExpertConversations(conversation.expert_slug),
  ])

  return <ChatView conversation={conversation} expert={expert} siblings={siblings} />
}
