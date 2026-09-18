/// <reference lib="webworker" />

import { computeLayout, type BrainLayout } from '@/lib/brain/layout'
import type { MapResponse } from '@/lib/api/types'

/**
 * The map's layout, off the main thread.
 *
 * The cloud is a fixed-length force simulation (300 ticks over up to 600
 * concepts), which costs a noticeable slice of a second on a phone. It runs to
 * rest here and is posted **once** — the map never visibly converges, under
 * reduced motion or otherwise, because a layout that moves while it settles is
 * a different picture every visit. The entrance is pulses, not motion.
 *
 * The concept positions are transferred, not copied.
 */

export type LayoutRequest = { type: 'layout'; map: MapResponse; generation: number }
export type LayoutResponse = { type: 'layout'; layout: BrainLayout; generation: number }

self.onmessage = (event: MessageEvent<LayoutRequest>) => {
  const { map, generation } = event.data
  const layout = computeLayout(map)
  const message: LayoutResponse = { type: 'layout', layout, generation }
  self.postMessage(message, [layout.concepts.buffer])
}
