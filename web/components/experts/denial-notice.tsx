import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/cn'
import type { EntitlementDenial } from '@/lib/api/types'

/**
 * The 402, rendered as a panel.
 *
 * The API's denial body is the payload the UI is meant to render — a code to
 * switch on, the numbers, and exactly one available remedy — so it is shown
 * whole rather than flattened into a toast.
 *
 * **There is no checkout.** The only remedy is to ask, which is why
 * `request_credits` becomes a `mailto:` and never a button that pretends to
 * take payment (web-production.md, rule 3). A fake upgrade path here would be
 * the single most misleading thing in the product.
 */
const REQUEST_EMAIL = 'credits@peritus.app'

export function DenialNotice({
  denial,
  className,
}: {
  denial: EntitlementDenial
  className?: string
}) {
  const subject = encodeURIComponent(`Credit request — ${denial.plan} plan`)
  const body = encodeURIComponent(
    `I would like more credits.\n\nPlan: ${denial.plan}\nTier I tried to build: ${denial.tier}\n` +
      (denial.required_credits !== undefined
        ? `Needed: ${denial.required_credits}\nAvailable: ${denial.available_credits ?? 0}\n`
        : ''),
  )

  return (
    <Notice
      tone="warn"
      className={cn('animate-in fade-in slide-in-from-bottom-1 duration-(--dur-2)', className)}
      title={denial.code === 'insufficient_credits' ? 'Not enough credits' : 'Not on your plan'}
      action={
        denial.remedy.kind === 'request_credits' ? (
          <a
            href={`mailto:${REQUEST_EMAIL}?subject=${subject}&body=${body}`}
            className="inline-flex h-(--row-h) items-center rounded-row bg-warn/15 px-3 text-sm font-medium text-warn transition-colors duration-(--dur-1) hover:bg-warn/25"
          >
            {denial.remedy.label}
          </a>
        ) : (
          // `change_tier` needs no button: the tier picker is already on screen
          // and the label says which tier to pick.
          <span className="text-xs text-fg-3">{denial.remedy.label}</span>
        )
      }
    >
      <p>{denial.message}</p>
      {denial.code === 'insufficient_credits' && denial.required_credits !== undefined && (
        <p className="mt-1 font-mono text-xs text-fg-3">
          needs {denial.required_credits} · has {denial.available_credits ?? 0}
        </p>
      )}
      {denial.allowed_tiers && denial.allowed_tiers.length > 0 && (
        <p className="mt-1 text-xs text-fg-3">
          Your plan includes {denial.allowed_tiers.join(', ')}.
        </p>
      )}
      <p className="mt-1.5 text-xs text-fg-3">{denial.remedy.detail}</p>
    </Notice>
  )
}
