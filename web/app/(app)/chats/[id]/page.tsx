import { ChatView } from '@/components/chat/chat-view'
import { getConversation, getExpertConversations, getExpertIfReadable } from '@/lib/api/data'
import type { ConversationDetail, ExpertWithCatalog } from '@/lib/api/types'

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
  const expert = await getExpertIfReadable(conversation.expert_slug)

  // The chat is the caller's, but the expert is not readable any more: it was
  // shared with them and the link has since been reset or turned off. The
  // transcript is still theirs to read; they just cannot ask anything new.
  if (!expert) {
    return (
      <ChatView
        conversation={conversation}
        expert={expertFromConversation(conversation)}
        siblings={[]}
        unavailable
      />
    )
  }

  const siblings = await getExpertConversations(conversation.expert_slug)
  return <ChatView conversation={conversation} expert={expert} siblings={siblings} />
}

/**
 * Enough of an expert to title and draw a chat whose expert can no longer be
 * fetched — from the columns the conversation already carries. Counts are
 * zero and readiness is pending because nothing here may be asked or opened.
 */
function expertFromConversation(conversation: ConversationDetail): ExpertWithCatalog {
  return {
    id: conversation.expert_id,
    name: conversation.expert_slug,
    topic: conversation.expert_topic,
    status: conversation.expert_status,
    build_active: false,
    tier: 'standard',
    readiness: 'pending',
    graph_expanded: false,
    persona_name: conversation.expert_persona_name,
    persona_bio: null,
    persona_style: null,
    avg_quality: null,
    key_concepts: [],
    source_count: 0,
    chunk_count: 0,
    node_count: 0,
    edge_count: 0,
    source_type_counts: {},
    avatar: null,
    // Its bytes are behind the same read rule, so the tile falls back to the monogram.
    picture: null,
    access: 'viewer',
    created_at: conversation.created_at,
    error: null,
    updated_at: conversation.last_message_at,
    catalog: {
      visibility: 'private',
      is_featured: false,
      catalog_rank: null,
      blurb: null,
      category: null,
      tags: [],
      published_at: null,
    },
  }
}
