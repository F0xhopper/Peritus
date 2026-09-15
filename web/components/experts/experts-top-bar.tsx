'use client'

import { TopBar } from '@/components/shell/top-bar'

/**
 * Home's bar, with no action of its own.
 *
 * It used to carry a "New expert" button — the fourth route to building on one
 * screen, beside the composer, the sidebar row and the rail's `+`. The composer
 * directly below is the one that should win, and a shortcut to it in the bar
 * only diluted it.
 */
export function ExpertsTopBar() {
  return <TopBar title="Home" />
}
