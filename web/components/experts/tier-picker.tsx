'use client'

import { useId, useRef } from 'react'

import { cn } from '@/lib/cn'
import { DEPTH } from '@/lib/build/copy'
import type { ExpertTier, TierPrice } from '@/lib/api/types'

/**
 * The tier choice, shared by the Home composer, `/experts/new` and expert
 * settings — so a rebuild and a first build cannot disagree about what a tier
 * costs or which ones the plan allows.
 *
 * `null` is **Auto**, and it is the default: sending no tier lets the API pick
 * the deepest one the caller's plan allows and balance affords, which is the
 * only choice guaranteed to be buildable. Picking a tier by hand is the
 * override.
 *
 * A tier outside `allowed_tiers` is disabled *with its reason shown*. A greyed
 * card with no explanation is the thing that makes a plan limit feel like a bug.
 */

export type TierChoice = ExpertTier | null

export function TierPicker({
  tiers,
  allowedTiers,
  value,
  onChange,
  creditsEnforced,
  balance,
  className,
}: {
  tiers: TierPrice[]
  /** From `billing/me`; null means the plan is unknown, so nothing is disabled. */
  allowedTiers: ExpertTier[] | null
  value: TierChoice
  onChange: (value: TierChoice) => void
  creditsEnforced: boolean
  balance: number | null
  className?: string
}) {
  const allowed = (tier: ExpertTier) => allowedTiers === null || allowedTiers.includes(tier)
  const group = useRef<HTMLDivElement>(null)
  const id = useId()

  // Radio-group keyboard behaviour: one tab stop, arrows move the selection
  // across the enabled options (a disabled tier is skipped, not landed on).
  const choices: TierChoice[] = [null, ...tiers.filter((t) => allowed(t.tier)).map((t) => t.tier)]
  const onKeyDown = (event: React.KeyboardEvent) => {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowDown'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? -1
          : 0
    if (!step) return
    event.preventDefault()
    const index = Math.max(0, choices.indexOf(value))
    const next = choices[(index + step + choices.length) % choices.length]
    onChange(next)
    requestAnimationFrame(() =>
      group.current?.querySelector<HTMLElement>('[role="radio"][aria-checked="true"]')?.focus()
    )
  }

  return (
    <div
      ref={group}
      role="radiogroup"
      aria-label="Depth"
      onKeyDown={onKeyDown}
      className={cn('grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4', className)}
    >
      <TierCard
        selected={value === null}
        onSelect={() => onChange(null)}
        title="Auto"
        blurb="The deepest tier your plan allows and your balance can pay for."
        cost={null}
        creditsEnforced={creditsEnforced}
        affordable
        describedBy={`${id}-auto`}
      />
      {tiers.map((tier) => {
        const included = allowed(tier.tier)
        const affordable = !creditsEnforced || balance === null || balance >= tier.credit_cost
        return (
          <TierCard
            key={tier.tier}
            selected={value === tier.tier}
            onSelect={() => onChange(tier.tier)}
            title={DEPTH[tier.tier]?.label ?? tier.tier}
            blurb={DEPTH[tier.tier]?.blurb ?? ''}
            cost={tier.credit_cost}
            creditsEnforced={creditsEnforced}
            describedBy={`${id}-${tier.tier}`}
            disabled={!included}
            disabledReason={included ? undefined : 'Not on your plan'}
            affordable={affordable}
          />
        )
      })}
    </div>
  )
}

function TierCard({
  selected,
  onSelect,
  title,
  blurb,
  cost,
  creditsEnforced,
  disabled,
  disabledReason,
  affordable,
  describedBy,
}: {
  selected: boolean
  onSelect: () => void
  title: string
  blurb: string
  cost: number | null
  creditsEnforced: boolean
  /** The id the blurb and any disabled reason carry, for `aria-describedby`. */
  describedBy: string
  disabled?: boolean
  disabledReason?: string
  affordable: boolean
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      // `aria-disabled`, not `disabled`: a disabled button cannot be focused
      // and its "Not on your plan" reason was invisible to assistive tech.
      aria-disabled={disabled || undefined}
      aria-describedby={describedBy}
      // Roving tab stop: the group is one stop; arrows move within it.
      tabIndex={selected ? 0 : -1}
      onClick={() => {
        if (!disabled) onSelect()
      }}
      className={cn(
        'flex flex-col rounded-card border p-3 text-left',
        // Ring colour on select, no scale — the card must not jump under the
        // finger that just tapped it.
        'transition-colors duration-(--dur-1)',
        selected ? 'border-expert bg-expert-soft' : 'border-border hover:border-fg-4',
        disabled && 'cursor-not-allowed opacity-50 hover:border-border'
      )}
    >
      <span className="flex items-baseline justify-between gap-2">
        {/* The selected card's text steps *up* a tone. `text-expert` is a grey,
            and on the lighter selected fill it left the chosen tier the
            dimmest card of the four — it read as disabled. */}
        <span className="text-sm font-medium text-fg">{title}</span>
        {creditsEnforced && cost !== null && (
          <span
            className={cn(
              'text-xs',
              !affordable && !disabled ? 'text-bad' : selected ? 'text-fg-2' : 'text-fg-3'
            )}
          >
            {cost} {cost === 1 ? 'credit' : 'credits'}
          </span>
        )}
      </span>
      <span
        id={describedBy}
        className={cn('mt-1 text-xs leading-snug', selected ? 'text-fg-2' : 'text-fg-3')}
      >
        {blurb}
        {disabledReason && <span className="mt-1.5 block text-warn">{disabledReason}</span>}
      </span>
      {!disabled && !affordable && (
        <span className="mt-1.5 text-xs text-bad">More credits than you have</span>
      )}
      {/* No dollar spend cap here: the card is priced in credits, and a second
          currency beside the first raised a question the page never answered. */}
    </button>
  )
}

/** "Holds 3 credits, you have 12." — the line under the picker. */
export function CostLine({
  tier,
  tiers,
  balance,
  creditsEnforced,
  className,
}: {
  tier: TierChoice
  tiers: TierPrice[]
  balance: number | null
  creditsEnforced: boolean
  className?: string
}) {
  if (!creditsEnforced) {
    return (
      <p className={cn('text-xs text-fg-3', className)}>
        Building is free here — credits are not being charged.
      </p>
    )
  }
  if (tier === null) {
    return (
      <p className={cn('text-xs text-fg-3', className)}>
        {balance === null
          ? 'Peritus picks the depth.'
          : `Peritus picks the deepest depth your ${balance} credits can pay for.`}
      </p>
    )
  }
  const price = tiers.find((t) => t.tier === tier)
  if (!price) return null
  const short = balance !== null && balance < price.credit_cost

  return (
    <p className={cn('text-xs', short ? 'text-bad' : 'text-fg-3', className)}>
      Holds {price.credit_cost} {price.credit_cost === 1 ? 'credit' : 'credits'}
      {balance !== null && `, you have ${balance}`}.{' '}
      {/* Credits are *held* while the build runs and refunded if it fails —
          worth saying, because "holds" is not "spends". */}
      <span className="text-fg-3">Refunded in full if the build fails.</span>
    </p>
  )
}
