import { cn } from '@/lib/cn'

/**
 * A placeholder with the same box as the thing it stands in for.
 *
 * Every `loading.tsx` is built from these at the real row heights and column
 * widths, which is what keeps CLS under 0.1: the skeleton and the content
 * occupy the same space, so nothing moves when the data lands.
 */
export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: React.CSSProperties
}) {
  return (
    <div
      aria-hidden="true"
      style={style}
      className={cn('animate-skeleton rounded-chip bg-raised', className)}
    />
  )
}

/**
 * The top bar, at its real height. `crumb` adds the avatar-and-name breadcrumb
 * an expert's pages carry; `action` reserves the one button on the right.
 */
export function SkeletonTopBar({
  crumb = false,
  action = false,
  titleWidth = 'w-24',
}: {
  crumb?: boolean
  action?: boolean
  titleWidth?: string
}) {
  return (
    <div className="flex h-topbar-touch shrink-0 items-center gap-2 border-b border-border-soft px-3 md:h-topbar md:px-4">
      {crumb && (
        <>
          <Skeleton className="size-5 rounded-chip" />
          <Skeleton className="hidden h-3.5 w-24 sm:block" />
        </>
      )}
      <Skeleton className={cn('h-3.5', titleWidth)} />
      {action && <Skeleton className="ml-auto h-8 w-24 rounded-row" />}
    </div>
  )
}
