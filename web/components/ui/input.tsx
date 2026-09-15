import { cn } from '@/lib/cn'

/**
 * Inputs and textareas.
 *
 * Height comes from `--row-h`, so both grow to 44px under a coarse pointer, and
 * the base layer in globals.css forces 16px type there to stop iOS zooming the
 * page on focus. The focus ring is `--expert`, which inside an expert's pages
 * means the field is in that expert's colour.
 */

const field = [
  'w-full rounded-row border border-border bg-raised px-2.5 text-sm text-fg',
  'placeholder:text-fg-3',
  'transition-[border-color,background-color] duration-(--dur-1)',
  'hover:border-fg-4',
  'focus:border-expert focus:outline-none',
  'disabled:cursor-not-allowed disabled:opacity-50',
  'aria-invalid:border-bad',
].join(' ')

export function Input({ className, ...props }: React.ComponentProps<'input'>) {
  return <input {...props} className={cn(field, 'h-(--row-h)', className)} />
}

export function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return <textarea {...props} className={cn(field, 'py-2 leading-relaxed', className)} />
}

export function Label({ className, ...props }: React.ComponentProps<'label'>) {
  return (
    <label
      {...props}
      className={cn('block text-label tracking-[0.04em] text-fg-3 uppercase', className)}
    />
  )
}

/**
 * A field's error slot with a reserved height.
 *
 * The `min-h` is the point: an error appearing must not move the submit button
 * out from under the pointer, which is exactly the layout shift the login card
 * is measured on.
 */
export function FieldError({ children }: { children?: React.ReactNode }) {
  return (
    <p
      aria-live="polite"
      className="min-h-4 text-xs text-bad transition-opacity duration-(--dur-2)"
    >
      {children}
    </p>
  )
}
