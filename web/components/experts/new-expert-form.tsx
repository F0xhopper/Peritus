'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useRef } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { DenialNotice } from '@/components/experts/denial-notice'
import { FieldError, Label, Textarea } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { CostLine, TierPicker } from '@/components/experts/tier-picker'
import { useStartBuild } from '@/hooks/use-start-build'
import type { ExpertTier, TierPrice } from '@/lib/api/types'

/**
 * The full build form.
 *
 * Below `md` the cost line and the Build button are a sticky footer above the
 * safe area: the tier cards stack there, and a submit button that has scrolled
 * off the bottom of a form is a submit button that does not exist.
 *
 * On a 402 the form keeps its height and a notice appears under it, rather than
 * the page reflowing around a new panel.
 */
const MAX_TOPIC = 300

const EXAMPLES = [
  'Varroa mite control in temperate beekeeping',
  'Measurement error in nutritional epidemiology',
  'Byzantine fault tolerance in production systems',
]

const schema = z.object({
  topic: z
    .string()
    .trim()
    .min(1, 'Name a subject')
    .max(MAX_TOPIC, `Keep it under ${MAX_TOPIC} characters`)
    // The server derives the slug from this and refuses a topic with nothing
    // sluggable in it, so catch that here rather than after a round trip.
    .refine((value) => /[a-z0-9]/i.test(value), 'Include at least one letter or number'),
  tier: z.union([z.literal('lite'), z.literal('standard'), z.literal('pro'), z.null()]),
})

type Values = z.infer<typeof schema>

export function NewExpertForm({
  initialTopic,
  tiers,
  allowedTiers,
  creditsEnforced,
  balance,
}: {
  initialTopic: string
  tiers: TierPrice[]
  allowedTiers: ExpertTier[] | null
  creditsEnforced: boolean
  balance: number | null
}) {
  const { start, submitting, denial, error, clear } = useStartBuild()
  const topicRef = useRef<HTMLTextAreaElement | null>(null)

  /**
   * Focus the field on a mouse, never on a touch device.
   *
   * `autoFocus` would open the software keyboard the moment the page appears,
   * covering the tier picker and the cost line before the user has read
   * either — and the design's own rule is that the keyboard must never hide a
   * form's submit button. In an effect rather than the `autoFocus` prop
   * because that prop is only honoured on mount, and the media query is not
   * knowable during the server render.
   */
  useEffect(() => {
    if (window.matchMedia('(pointer: fine)').matches) topicRef.current?.focus()
  }, [])

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { topic: initialTopic, tier: null },
    mode: 'onSubmit',
  })

  const tier = form.watch('tier')
  const topic = form.watch('topic')

  // The registration's own ref has to be kept and called alongside ours, or
  // react-hook-form loses the element and the field stops being read.
  const { ref: registerTopic, ...topicField } = form.register('topic', {
    onChange: () => {
      if (denial || error) clear()
    },
  })

  const onSubmit = form.handleSubmit(async ({ topic: value, tier: chosen }) => {
    await start(value, chosen)
  })

  return (
    <form onSubmit={onSubmit} className="mt-6 pb-24 md:pb-0" noValidate>
      <Label htmlFor="topic">Subject</Label>
      <Textarea
        id="topic"
        rows={2}
        placeholder="Varroa mite control in temperate beekeeping"
        aria-invalid={form.formState.errors.topic ? true : undefined}
        {...topicField}
        ref={(element) => {
          registerTopic(element)
          topicRef.current = element
        }}
        className="mt-1.5"
      />
      <div className="flex items-start justify-between gap-3">
        <FieldError>{form.formState.errors.topic?.message}</FieldError>
        <span className="mt-0.5 shrink-0 text-xs text-fg-3">
          {topic.length} / {MAX_TOPIC}
        </span>
      </div>

      <div className="mt-1 flex flex-wrap gap-1.5">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            onClick={() => form.setValue('topic', example, { shouldValidate: true })}
            className="rounded-chip bg-raised px-2 py-1 text-left text-xs text-fg-3 transition-colors duration-(--dur-1) hover:bg-border hover:text-fg-2"
          >
            {example}
          </button>
        ))}
      </div>

      <div className="mt-6">
        <Label>Depth</Label>
        <TierPicker
          tiers={tiers}
          allowedTiers={allowedTiers}
          value={tier}
          onChange={(next) => form.setValue('tier', next)}
          creditsEnforced={creditsEnforced}
          balance={balance}
          className="mt-1.5 lg:grid-cols-2"
        />
      </div>

      {denial && <DenialNotice denial={denial} className="mt-4" />}
      {error && (
        <Notice tone="bad" className="mt-4">
          {error}
        </Notice>
      )}

      {/* Inline at `md` and up; a sticky footer below, above the safe area. */}
      <div className="mt-6 hidden items-center justify-between gap-4 md:flex">
        <CostLine
          tier={tier}
          tiers={tiers}
          balance={balance}
          creditsEnforced={creditsEnforced}
        />
        <Button type="submit" variant="primary" size="lg" loading={submitting} minWidth={120}>
          Build
        </Button>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-bg px-4 pt-3 pb-safe-4 md:hidden">
        <CostLine
          tier={tier}
          tiers={tiers}
          balance={balance}
          creditsEnforced={creditsEnforced}
          className="mb-2"
        />
        <Button
          type="submit"
          variant="primary"
          size="lg"
          loading={submitting}
          className="w-full"
        >
          Build
        </Button>
      </div>
    </form>
  )
}
