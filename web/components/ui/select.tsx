import { cn } from '@/lib/cn'

/**
 * A native `<select>`.
 *
 * Deliberately native, and only used below `lg` where the ledger's sort control
 * has no room for a segmented one: the platform picker is a better control on a
 * phone than any listbox this app could build, it is already accessible, and it
 * does not need a portal inside a scrolling sheet.
 */
export function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <select
      {...props}
      className={cn(
        'h-(--row-h) rounded-row border border-border bg-raised px-2 pr-7 text-sm text-fg',
        'appearance-none bg-[length:12px] bg-[position:right_8px_center] bg-no-repeat',
        "bg-[url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' fill='none' stroke='%236b6b73' stroke-width='1.5'><path d='M3 4.5 6 7.5 9 4.5'/></svg>\")]",
        'transition-colors duration-(--dur-1) hover:border-fg-4 focus:border-expert focus:outline-none',
        className,
      )}
    />
  )
}
