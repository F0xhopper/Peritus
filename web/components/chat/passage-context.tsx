'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { cn } from '@/lib/cn'
import type { PassageWindow } from '@/lib/api/types'

/**
 * The cited passage, in the source it came from.
 *
 * A quote with a bibliography entry is a claim; the quote with the paragraph
 * before and after it is the evidence — and it is where a citation that does
 * not support its sentence becomes obvious without leaving the answer.
 *
 * **The window replaces the quote rather than repeating it.** The citation
 * carries an excerpt and the window carries the whole chunk that excerpt came
 * from, so rendering both put the same sentence on screen twice — and made the
 * panel's own test ambiguous about which one it meant. Until the window
 * arrives (or if it never does) the excerpt is the evidence; once it has, the
 * cited paragraph *inside* the window is.
 *
 * **No spinner.** The quote is on screen from the first frame and the context
 * replaces it in place. A failure here must never make the panel look broken,
 * because the panel was already useful.
 *
 * **It says what it is showing.** No original is kept — a fetched PDF or page
 * is never stored, only the cleaned extraction — so this is *the text the
 * expert read*, and the line at the foot says so and links to the original
 * where there is one.
 */
export function PassageContext({
  slug,
  sourceId,
  chunkId,
  quote,
}: {
  slug: string
  sourceId: number
  chunkId: number
  /** The citation's own excerpt, shown until — and instead of — the window. */
  quote?: string | null
}) {
  const [window_, setWindow] = useState<PassageWindow | null>(null)

  // Clearing the last citation's context belongs in render, not in the effect:
  // setting state synchronously inside one cascades a render, and the rule that
  // catches it (`react-hooks/set-state-in-effect`) is on for exactly this.
  const key = `${sourceId}:${chunkId}`
  const [loadedFor, setLoadedFor] = useState(key)
  if (loadedFor !== key) {
    setLoadedFor(key)
    setWindow(null)
  }

  useEffect(() => {
    const controller = new AbortController()
    void fetch(
      `/api/experts/${encodeURIComponent(slug)}/sources/${sourceId}/passages?around=${chunkId}&before=2&after=2`,
      { signal: controller.signal }
    )
      .then((response) => (response.ok ? (response.json() as Promise<PassageWindow>) : null))
      .then((data) => {
        if (data) setWindow(data)
      })
      .catch(() => {
        /* the quote above is still there; that is the fallback */
      })
    return () => controller.abort()
  }, [slug, sourceId, chunkId])

  // Nothing yet, or nothing worth calling context: the excerpt stands alone.
  if (!window_ || window_.passages.length <= 1) {
    return quote ? (
      <blockquote className="rounded-card bg-expert-soft p-2.5 text-fg-2">{quote}</blockquote>
    ) : null
  }

  const first = window_.passages[0]
  return (
    <section aria-label="The passage in its source">
      <p className="text-label tracking-[0.04em] text-fg-3 uppercase">In context</p>
      {first.section && (
        <p className="mt-1 text-xs text-fg-3">
          {first.section}
          {first.paragraph_n !== null && ` · ¶ ${first.paragraph_n}`}
        </p>
      )}
      <div className="mt-1.5 space-y-2 text-sm leading-relaxed">
        {window_.passages.map((passage) => (
          <p
            key={passage.chunk_id}
            className={cn(
              passage.chunk_id === window_.cited
                ? // The cited passage, on the expert's wash: the chunk, never a
                  // sentence within it — the faithfulness check judges whole
                  // passages, and marking one sentence would claim a precision
                  // the system does not have.
                  'rounded-card bg-expert-soft px-2.5 py-2 text-fg'
                : 'px-2.5 text-fg-3'
            )}
          >
            {passage.text}
          </p>
        ))}
      </div>
      <p className="mt-2 px-2.5 text-xs text-fg-3">
        This is the text the expert read, as extracted.
        {window_.source.url && (
          <>
            {' '}
            <a
              href={window_.source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-fg-2"
            >
              The original
            </a>{' '}
            may differ.
          </>
        )}
      </p>
      {window_.whole_available && (
        <Link
          href={`/experts/${slug}/sources/${sourceId}/read?at=${chunkId}`}
          className="mt-2 inline-flex h-(--row-h) items-center rounded-row border border-border px-2.5 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
        >
          Read the whole source
        </Link>
      )}
    </section>
  )
}
