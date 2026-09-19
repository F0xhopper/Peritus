import { Sparkles } from 'lucide-react'

import { BuildingNow } from '@/components/experts/building-now'
import { ExpertCard } from '@/components/experts/expert-card'
import { RecentChats } from '@/components/experts/recent-chats'
import { TopicComposer } from '@/components/experts/topic-composer'
import { ExpertsTopBar } from '@/components/experts/experts-top-bar'
import { Empty } from '@/components/ui/empty'
import { StatTile } from '@/components/ui/stat-tile'
import { isBuilding } from '@/components/ui/status-dot'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/format'
import { getBilling, getConversations, getExperts } from '@/lib/api/data'

export const metadata = { title: 'Home' }

export default async function ExpertsHomePage() {
  const [experts, conversations, credits] = await Promise.all([
    getExperts('/experts'),
    getConversations(8, '/experts'),
    getBilling('/experts').catch(() => null),
  ])

  const building = experts.filter(isBuilding)
  const sources = experts.reduce((sum, expert) => sum + expert.source_count, 0)
  // Every credit element is hidden when the API is not enforcing them, rather
  // than showing a balance that means nothing (web-production.md, rule 3).
  const showCredits = credits?.credits_enforced === true

  return (
    <>
      <ExpertsTopBar />

      <div className="scroll-col flex-1">
        {/* One measure for the whole page, and one vertical rhythm: `mt-6`
            between sections, `mt-2` between a label and what it labels. The
            page used to mix `mt-5`, `mt-6` and `mt-8`, which read as three
            different gaps doing the same job. */}
        <div className="mx-auto w-full max-w-6xl px-4 pt-5 pb-12 md:px-6">
          {/* The top bar already says Home; on a phone a second, 24px "Home"
              spent the first screen on chrome. Kept for screen readers. */}
          <h1 className="sr-only text-title font-medium text-fg md:not-sr-only">Home</h1>
          <p className="hidden text-sm text-fg-3 md:mt-1 md:block">
            Every expert you have built, and what each one is made of.
          </p>

          <div className="md:mt-6">
            <TopicComposer
              tiers={credits?.tiers ?? []}
              allowedTiers={credits?.plan.allowed_tiers ?? null}
              creditsEnforced={showCredits}
              balance={credits?.balance ?? null}
              autoFocus={experts.length === 0}
            />
          </div>

          {/* One line of text on a phone, where four tiles pushed the expert
              cards — the page — a screen and a half down. */}
          <p className="mt-3 text-xs text-fg-3 md:hidden">
            {plural(experts.length, 'expert')}
            {building.length > 0 && <> · {building.length} building</>}
            {showCredits && <> · {plural(credits.balance, 'credit')}</>}
          </p>

          {/* Only tiles that say something: Building appears while a build runs,
              and "can answer" is on each card already. The grid is as wide as
              the tiles in it, so two do not sit in a four-column row. */}
          <div
            className={cn(
              'mt-6 hidden gap-3 md:grid',
              building.length > 0 ? 'grid-cols-3' : 'grid-cols-2'
            )}
          >
            <StatTile label="Experts" value={experts.length} />
            {building.length > 0 && (
              <StatTile label="Building" value={building.length} tone="warn" />
            )}
            {showCredits ? (
              <StatTile
                label="Credits"
                value={credits.balance}
                hint={
                  credits.held > 0 ? `${credits.held} held by a build` : credits.plan.display_name
                }
              />
            ) : (
              <StatTile label="Sources" value={sources} hint="across every expert" />
            )}
          </div>

          {building.length > 0 && (
            <div className="mt-6 space-y-2">
              {building.map((expert) => (
                <BuildingNow key={expert.id} expert={expert} />
              ))}
            </div>
          )}

          {experts.length === 0 ? (
            <Empty icon={Sparkles} className="mt-8">
              Type a topic above and Peritus will search for sources, screen them, and build an
              expert that answers with citations.
            </Empty>
          ) : (
            <section className="mt-6">
              <h2 className="text-label tracking-[0.04em] text-fg-3 uppercase">Experts</h2>
              {/* Three across at most: at four the cards were too narrow to hold a
                  name, a subject and a sentence of About without truncating
                  all three. */}
              <div className="mt-3 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {experts.map((expert, index) => (
                  <ExpertCard
                    key={expert.id}
                    expert={expert}
                    // First-paint stagger only, and capped at eight: a
                    // refresh or a re-sort must be instant.
                    stagger={index < 8 ? index : null}
                  />
                ))}
              </div>
            </section>
          )}

          {/* `lg:hidden` is not a duplicate rendered twice: from `lg` the
              sidebar beside this page *is* the chat list, and repeating it here
              was the same six rows twice on one screen. Below `lg` there is no
              sidebar, so this is the only way to reach a chat from Home. */}
          {conversations.length > 0 && (
            <section className="mt-6 lg:hidden">
              <h2 className="text-label tracking-[0.04em] text-fg-3 uppercase">Recent chats</h2>
              <RecentChats conversations={conversations} experts={experts} className="mt-2" />
            </section>
          )}
        </div>
      </div>
    </>
  )
}
