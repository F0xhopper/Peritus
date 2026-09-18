import { cn } from '@/lib/cn'

/**
 * shadcn/ui's `Card` family on this app's surfaces: `bg-panel` on `bg-bg`,
 * a border only because the auth card floats alone on the page (AGENTS.md:
 * depth is the surface step; a lone card on the ground needs its edge).
 */

export function Card({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="card"
      className={cn(
        'flex flex-col gap-5 rounded-panel border border-border bg-panel py-5',
        className
      )}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div data-slot="card-header" className={cn('flex flex-col gap-1 px-5', className)} {...props} />
  )
}

export function CardTitle({ className, ...props }: React.ComponentProps<'h1'>) {
  return (
    <h1
      data-slot="card-title"
      className={cn('text-lg leading-snug font-medium text-fg', className)}
      {...props}
    />
  )
}

export function CardDescription({ className, ...props }: React.ComponentProps<'p'>) {
  return (
    <p data-slot="card-description" className={cn('text-sm text-fg-3', className)} {...props} />
  )
}

export function CardContent({ className, ...props }: React.ComponentProps<'div'>) {
  return <div data-slot="card-content" className={cn('px-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div data-slot="card-footer" className={cn('flex items-center px-5', className)} {...props} />
  )
}
