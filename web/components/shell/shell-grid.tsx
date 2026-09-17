'use client'

import { useShell } from '@/components/shell/shell-context'
import { cn } from '@/lib/cn'

/**
 * The shell's grid, minus the sidebar's track when it is folded away.
 *
 * A client component only because the column template depends on the collapse
 * preference; the preference itself arrives from the server with the first
 * HTML, so this still decides nothing after paint.
 */
export function ShellGrid({ children }: { children: React.ReactNode }) {
  const { sidebarCollapsed } = useShell()

  return (
    <div
      className={cn(
        'grid h-dvh grid-cols-1 overflow-hidden md:grid-cols-[56px_minmax(0,1fr)]',
        sidebarCollapsed
          ? 'lg:grid-cols-[56px_minmax(0,1fr)] xl:grid-cols-[56px_minmax(0,1fr)_auto]'
          : 'lg:grid-cols-[56px_260px_minmax(0,1fr)] xl:grid-cols-[56px_260px_minmax(0,1fr)_auto]'
      )}
    >
      {children}
    </div>
  )
}
