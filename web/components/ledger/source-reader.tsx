'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

import { TopBar } from '@/components/shell/top-bar'
import { Notice } from '@/components/ui/notice'
import { MenuItem } from '@/components/ui/menu'
import { cn } from '@/lib/cn'
import { formatInt, hostOf } from '@/lib/format'
import { sourceKind } from '@/lib/source-kind'
import type { ExpertWithCatalog, PassageWindow } from '@/lib/api/types'

/**
 * A source's text, at reading width, opened at the cited passage.
 *
 * Three things this page has to be honest about, and all three are one line
 * each rather than a disclaimer block:
 *
 * **It is the extraction, not the original.** No original is kept — a fetched
 * PDF or page is never stored — and cleaning can drop a great deal (one book
 * lost most of its bulk to a table of contents). The line at the top says so
 * and links out where there is a link.
 *
 * **Sometimes it is only a window.** The API reproduces a whole source only for
 * the kinds it may; for everything else the same request returns the passages
 * around the citation. The page renders what came back and says which it is,
 * rather than promising a whole text it was not given.
 *
 * **The cited passage is marked, not the sentence.** The faithfulness check
 * judges whole passages; marking one sentence inside one would claim a
 * precision the system does not have.
 */
export function SourceReader({
  expert,
  window: reader,
}: {
  expert: ExpertWithCatalog
  window: PassageWindow
}) {
  const router = useRouter()
  const { source, passages, cited, scope } = reader

  // The cited passage is rarely the first: bring it into view once, after the
  // page is up, rather than asking the reader to hunt for the highlight.
  useEffect(() => {
    if (cited === null) return
    const target = document.getElementById(`p-${cited}`)
    if (!target) return
    const still = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    target.scrollIntoView({ block: 'center', behavior: still ? 'auto' : 'smooth' })
  }, [cited])

  // Where each section begins, computed before render rather than by mutating a
  // cursor inside `map` — a heading is a property of the list, not of the pass
  // over it.
  const opensSection = new Set(
    passages
      .filter(
        (passage, index) => passage.section && passage.section !== passages[index - 1]?.section
      )
      .map((passage) => passage.chunk_id)
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <TopBar
        expert={expert}
        title={source.title}
        overflow={
          <>
            <MenuItem
              onClick={() => router.push(`/experts/${expert.name}/sources?source=${source.id}`)}
            >
              The source record
            </MenuItem>
          </>
        }
      />

      <div className="scroll-col flex-1">
        <div className="mx-auto w-full max-w-[680px] px-4 pt-5 pb-16 md:px-6">
          <header>
            <h1 className="text-title font-medium text-fg">{source.title}</h1>
            <p className="mt-1 text-sm text-fg-3">
              {source.author && <>{source.author} · </>}
              {sourceKind(source.source_type)} · {formatInt(source.passage_count)} passages
            </p>
            <p className="mt-2 text-xs leading-relaxed text-fg-3">
              This is the text the expert read, as extracted — not the original.
              {source.url && (
                <>
                  {' '}
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="underline underline-offset-2 hover:text-fg-2"
                  >
                    The original is at {hostOf(source.url)}
                  </a>
                  .
                </>
              )}
            </p>
          </header>

          {scope === 'window' && (
            <Notice tone="info" className="mt-4">
              Only the passages around the citation are shown. This source is not one Peritus may
              reproduce in full — its record and a link to the original are on the{' '}
              <Link
                href={`/experts/${expert.name}/sources?source=${source.id}`}
                className="text-fg underline underline-offset-2"
              >
                Sources page
              </Link>
              .
            </Notice>
          )}

          <article className="mt-6 space-y-3 text-base leading-relaxed text-fg-2">
            {passages.map((passage) => {
              return (
                <div key={passage.chunk_id}>
                  {opensSection.has(passage.chunk_id) && (
                    <h2 className="mt-6 mb-2 text-label tracking-[0.04em] text-fg-3 uppercase">
                      {passage.section}
                    </h2>
                  )}
                  <p
                    id={`p-${passage.chunk_id}`}
                    className={cn(
                      'scroll-mt-20 rounded-card px-3 py-2',
                      passage.chunk_id === cited && 'bg-expert-soft text-fg'
                    )}
                  >
                    {passage.text}
                  </p>
                </div>
              )
            })}
          </article>
        </div>
      </div>
    </div>
  )
}
