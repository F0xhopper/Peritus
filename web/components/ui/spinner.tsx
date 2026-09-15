import { cn } from '@/lib/cn'

/**
 * The only spinner in the product, and only ever inside a button.
 *
 * Anything page- or panel-sized gets a `Skeleton` that matches the final
 * layout's heights instead. Under reduced motion the arc stops turning and
 * stays a static ring, which still reads as "working".
 */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={cn('size-4 animate-spin motion-reduce:animate-none', className)}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.25" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
