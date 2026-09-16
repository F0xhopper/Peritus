'use client'

import { Button as BaseButton } from '@base-ui/react/button'
import { cva, type VariantProps } from 'class-variance-authority'
import Link from 'next/link'

import { cn } from '@/lib/cn'
import { Spinner } from '@/components/ui/spinner'

/**
 * The one button.
 *
 * `primary` is `--accent`, which is **monochrome** — ink on paper, or paper on
 * ink. It used to be `--expert`, and that was the single worst colour decision
 * in the app: outside an expert's own pages `--expert` falls back to the root
 * hue, so every primary button in the product was violet, including the ones on
 * Home and in the composer. Colour here now means state (ok/warn/bad), and
 * nothing else.
 *
 * `loading` swaps the label for a spinner *in place* — the button keeps its
 * width, so nothing beside it moves. That is the only spinner in the product;
 * anything page-sized gets a skeleton instead.
 */

const button = cva(
  [
    'relative inline-flex shrink-0 select-none items-center justify-center gap-1.5',
    'text-sm font-medium whitespace-nowrap',
    'transition-[background-color,color,border-color,opacity,transform] duration-(--dur-1) ease-(--ease-out)',
    'active:scale-[0.98]',
    'disabled:pointer-events-none disabled:opacity-50 data-disabled:pointer-events-none data-disabled:opacity-50',
  ],
  {
    variants: {
      variant: {
        // `opacity`, not `brightness`: near-white cannot get brighter, so the
        // old hover was invisible in the dark theme.
        primary: 'bg-accent text-accent-fg hover:opacity-90',
        secondary: 'bg-raised text-fg hover:bg-border',
        outline: 'border border-border text-fg-2 hover:bg-raised hover:text-fg',
        ghost: 'text-fg-2 hover:bg-raised hover:text-fg',
        danger: 'bg-bad/12 text-bad hover:bg-bad/20',
        link: 'text-fg underline-offset-2 hover:underline',
      },
      size: {
        // Heights come from the `--row-h` family, so every control grows to
        // 44px under a coarse pointer without a single component knowing.
        sm: 'h-(--icon-btn-sm) rounded-chip px-2 text-xs',
        md: 'h-(--row-h) rounded-row px-3',
        /**
         * `md`, plus "be square once the label is hidden".
         *
         * Every top-bar action hides its label below `sm` (`hidden sm:inline`)
         * and used to keep `px-3` doing it — so on a phone the Chat button was a
         * 38×44 rounded rectangle standing between two 44×44 icon buttons,
         * wearing the padding of a word it was no longer showing. The width and
         * the height come from the same token pair, so it is square under both
         * pointers.
         */
        action: 'h-(--row-h) w-(--icon-btn) rounded-row px-0 sm:w-auto sm:pl-2.5 sm:pr-3',
        lg: 'h-(--btn-lg) rounded-row px-4',
        icon: 'size-(--icon-btn) rounded-row',
        'icon-sm': 'size-(--icon-btn-sm) rounded-chip',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  }
)

export interface ButtonProps
  extends Omit<React.ComponentProps<typeof BaseButton>, 'className'>, VariantProps<typeof button> {
  className?: string
  loading?: boolean
  /** Minimum width, so a label→spinner swap cannot change the layout. */
  minWidth?: number
}

export function Button({
  className,
  variant,
  size,
  loading = false,
  minWidth,
  children,
  disabled,
  style,
  ...props
}: ButtonProps) {
  return (
    <BaseButton
      {...props}
      disabled={disabled || loading}
      data-loading={loading ? '' : undefined}
      style={minWidth ? { minWidth, ...style } : style}
      className={cn(button({ variant, size }), className)}
    >
      {/* Both states are rendered; only one is visible. Keeping the label in
          the layout is what holds the width steady through the swap. */}
      <span
        className={cn(
          'inline-flex items-center gap-1.5 transition-opacity duration-(--dur-1)',
          loading && 'opacity-0'
        )}
      >
        {children}
      </span>
      {loading && (
        <span className="absolute inset-0 grid place-items-center">
          <Spinner className="size-4" />
        </span>
      )}
    </BaseButton>
  )
}

/**
 * A link that looks like a button.
 *
 * A plain `next/link` with the button's classes, deliberately **not** Base UI's
 * `Button` with `render`. Base UI needs `nativeButton={false}` to compose onto a
 * non-button element, and that puts `role="button"` on the anchor — which
 * overrides the implicit link role, so a screen reader announces "button" for
 * something that navigates, and the usual link affordances (open in a new tab,
 * copy the address, see the target in the status bar) stop being described.
 *
 * Base UI's Button earns its keep for real buttons, where it handles the
 * disabled-but-focusable case. An anchor needs none of that.
 */
export function ButtonLink({
  className,
  variant,
  size,
  children,
  href,
  ...props
}: Omit<React.ComponentProps<typeof Link>, 'className'> &
  VariantProps<typeof button> & {
    className?: string
    href: React.ComponentProps<typeof Link>['href']
  }) {
  return (
    <Link {...props} href={href} className={cn(button({ variant, size }), className)}>
      {children}
    </Link>
  )
}

export { button as buttonStyles }
