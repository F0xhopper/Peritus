import { cn } from '@/lib/cn'

/**
 * The wordmark: a monogram tile and the name.
 *
 * The tile is the same rounded square the expert sigils use, at the brand
 * accent instead of an expert hue — so the product's own mark reads as the same
 * family of object as the things it builds.
 */
export function Wordmark({ className, markOnly }: { className?: string; markOnly?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      <span
        aria-hidden="true"
        className="grid aspect-square h-full place-items-center rounded-[0.3em] bg-accent/15 ring-1 ring-accent/40 ring-inset"
      >
        <span className="text-[0.62em] leading-none font-semibold text-accent">P</span>
      </span>
      {!markOnly && (
        <span className="text-[0.95em] leading-none font-medium tracking-tight text-fg">
          Peritus
        </span>
      )}
    </span>
  )
}
