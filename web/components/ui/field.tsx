import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/cn'

/**
 * shadcn/ui's `Field` family, ported onto this app's tokens.
 *
 * The API — `FieldGroup` › `Field` › `FieldLabel` / control / `FieldDescription`
 * / `FieldError`, plus `FieldSeparator` for "or" — is shadcn's, so a form reads
 * the way the shadcn blocks do (the sign-in forms are `login-03`). The classes
 * are not: shadcn's `text-muted-foreground`, `text-destructive` and
 * `bg-background` are `text-fg-3`, `text-bad` and `bg-panel` here, and there is
 * no `Label` or `Separator` primitive to depend on.
 *
 * One deliberate departure: `FieldError` keeps a reserved line when empty
 * (`reserve`), because an error appearing must not move the submit button out
 * from under the pointer — the CLS the auth pages are measured on.
 */

export function FieldSet({ className, ...props }: React.ComponentProps<'fieldset'>) {
  return (
    <fieldset data-slot="field-set" className={cn('flex flex-col gap-5', className)} {...props} />
  )
}

export function FieldLegend({
  className,
  variant = 'legend',
  ...props
}: React.ComponentProps<'legend'> & { variant?: 'legend' | 'label' }) {
  return (
    <legend
      data-slot="field-legend"
      data-variant={variant}
      className={cn(
        'mb-2 font-medium text-fg',
        'data-[variant=label]:text-sm data-[variant=legend]:text-lg',
        className
      )}
      {...props}
    />
  )
}

export function FieldGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="field-group"
      className={cn('group/field-group flex w-full flex-col gap-5', className)}
      {...props}
    />
  )
}

const fieldVariants = cva('group/field flex w-full gap-2', {
  variants: {
    orientation: {
      vertical: 'flex-col [&>*]:w-full [&>.sr-only]:w-auto',
      horizontal: 'flex-row items-center [&>[data-slot=field-label]]:flex-auto',
    },
  },
  defaultVariants: { orientation: 'vertical' },
})

export function Field({
  className,
  orientation = 'vertical',
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof fieldVariants>) {
  return (
    <div
      role="group"
      data-slot="field"
      data-orientation={orientation}
      className={cn(fieldVariants({ orientation }), className)}
      {...props}
    />
  )
}

export function FieldContent({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="field-content"
      className={cn('flex flex-1 flex-col gap-1 leading-snug', className)}
      {...props}
    />
  )
}

export function FieldLabel({ className, ...props }: React.ComponentProps<'label'>) {
  return (
    <label
      data-slot="field-label"
      className={cn(
        'flex w-fit items-center gap-2 text-sm leading-snug font-medium text-fg',
        'group-data-[disabled=true]/field:opacity-50',
        className
      )}
      {...props}
    />
  )
}

export function FieldTitle({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="field-title"
      className={cn('flex w-fit items-center gap-2 text-sm font-medium text-fg', className)}
      {...props}
    />
  )
}

export function FieldDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return (
    <p
      data-slot="field-description"
      className={cn(
        'text-xs leading-normal text-fg-3',
        '[&_a]:text-fg-2 [&_a]:underline [&_a]:underline-offset-4 [&_a:hover]:text-fg',
        className
      )}
      {...props}
    />
  )
}

export function FieldSeparator({
  children,
  className,
  ...props
}: React.ComponentProps<'div'> & { children?: React.ReactNode }) {
  return (
    <div
      data-slot="field-separator"
      aria-hidden={children ? undefined : true}
      className={cn('relative flex h-5 items-center text-xs', className)}
      {...props}
    >
      <span className="absolute inset-x-0 top-1/2 h-px bg-border-soft" />
      {children && (
        <span className="relative mx-auto block w-fit bg-panel px-2 text-fg-3">{children}</span>
      )}
    </div>
  )
}

export function FieldError({
  className,
  children,
  errors,
  reserve = false,
  ...props
}: React.ComponentProps<'p'> & {
  errors?: Array<{ message?: string } | undefined>
  /** Keep a line's height when empty, so an error cannot shift what follows. */
  reserve?: boolean
}) {
  const messages = [
    ...new Set((errors ?? []).map((error) => error?.message).filter(Boolean) as string[]),
  ]
  const content = children ?? (messages.length ? messages.join(' ') : null)
  if (!content && !reserve) return null
  return (
    <p
      data-slot="field-error"
      aria-live="polite"
      className={cn('text-xs text-bad', reserve && 'min-h-4', className)}
      {...props}
    >
      {content}
    </p>
  )
}
