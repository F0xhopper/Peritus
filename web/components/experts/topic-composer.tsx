'use client'

import { ArrowRight, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Collapse } from '@/components/ui/collapse'
import { DenialNotice } from '@/components/experts/denial-notice'
import { CostLine, TierPicker, type TierChoice } from '@/components/experts/tier-picker'
import { Notice } from '@/components/ui/notice'
import { useStartBuild } from '@/hooks/use-start-build'
import { cn } from '@/lib/cn'
import type { ExpertTier, TierPrice } from '@/lib/api/types'

/**
 * "Build an expert on…" at the top of Home.
 *
 * Enter submits at Auto, which is the whole point: a topic is a complete,
 * valid request and choosing a tier is an override, not a step. *Options*
 * expands the picker inline with the grid-rows collapse rather than navigating
 * to `/experts/new`, so the common case is one field and one key.
 */
const MAX_TOPIC = 300

export function TopicComposer({
  tiers,
  allowedTiers,
  creditsEnforced,
  balance,
  autoFocus,
}: {
  tiers: TierPrice[]
  allowedTiers: ExpertTier[] | null
  creditsEnforced: boolean
  balance: number | null
  autoFocus?: boolean
}) {
  const [topic, setTopic] = useState('')
  const [tier, setTier] = useState<TierChoice>(null)
  const [showOptions, setShowOptions] = useState(false)
  const { start, submitting, denial, error, clear } = useStartBuild()
  const input = useRef<HTMLInputElement>(null)

  // Focus on a mouse, never on touch — the same reasoning as the other two
  // composers: a keyboard that opens on arrival covers the page.
  useEffect(() => {
    if (autoFocus && window.matchMedia('(pointer: fine)').matches) input.current?.focus()
  }, [autoFocus])

  const tooLong = topic.length > MAX_TOPIC
  const canSubmit = topic.trim().length > 0 && !tooLong && !submitting

  const submit = (event: React.FormEvent) => {
    event.preventDefault()
    if (!canSubmit) return
    void start(topic, tier)
  }

  return (
    <form onSubmit={submit} className="rounded-card bg-panel p-3">
      <div className="flex items-center gap-2">
        <input
          ref={input}
          value={topic}
          onChange={(event) => {
            setTopic(event.target.value)
            if (denial || error) clear()
          }}
          placeholder="Build an expert on…"
          aria-label="Topic"
          maxLength={MAX_TOPIC + 40}
          className="h-(--row-h) min-w-0 flex-1 bg-transparent text-base text-fg placeholder:text-fg-3 focus:outline-none md:text-sm"
        />
        <Button
          type="submit"
          variant="primary"
          size="md"
          disabled={!canSubmit}
          loading={submitting}
          minWidth={92}
        >
          Build
          <ArrowRight className="size-3.5" />
        </Button>
      </div>

      <div className="mt-1.5 flex items-center gap-3">
        <button
          type="button"
          onClick={() => setShowOptions((value) => !value)}
          aria-expanded={showOptions}
          className="inline-flex min-h-(--row-h) items-center gap-1 text-xs text-fg-3 transition-colors duration-(--dur-1) hover:text-fg-2"
        >
          <ChevronDown
            aria-hidden="true"
            className={cn(
              'size-3 transition-transform duration-(--dur-2) ease-(--ease-out)',
              showOptions && 'rotate-180'
            )}
          />
          Options
        </button>
        {!showOptions && (
          <CostLine tier={tier} tiers={tiers} balance={balance} creditsEnforced={creditsEnforced} />
        )}
        {tooLong && (
          <span className="ml-auto text-xs text-bad">
            {topic.length} / {MAX_TOPIC}
          </span>
        )}
      </div>

      <Collapse open={showOptions}>
        <div className="pt-3">
          <TierPicker
            tiers={tiers}
            allowedTiers={allowedTiers}
            value={tier}
            onChange={setTier}
            creditsEnforced={creditsEnforced}
            balance={balance}
          />
          <CostLine
            tier={tier}
            tiers={tiers}
            balance={balance}
            creditsEnforced={creditsEnforced}
            className="mt-2"
          />
        </div>
      </Collapse>

      {/* The form keeps its height while a notice enters, so the Build button
          does not move under the pointer that just pressed it. */}
      {denial && <DenialNotice denial={denial} className="mt-3" />}
      {error && (
        <Notice
          tone="bad"
          className="mt-3 animate-in duration-(--dur-2) fade-in slide-in-from-bottom-1"
        >
          {error}
        </Notice>
      )}
    </form>
  )
}
