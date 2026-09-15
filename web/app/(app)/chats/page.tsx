import { ChatsListPage } from '@/components/chat/chats-list-page'
import { getConversations, getExperts } from '@/lib/api/data'

export const metadata = { title: 'Chats' }

export default async function ChatsPage() {
  const [conversations, experts] = await Promise.all([
    getConversations(50, '/chats'),
    getExperts('/chats'),
  ])
  return <ChatsListPage conversations={conversations} experts={experts} />
}
