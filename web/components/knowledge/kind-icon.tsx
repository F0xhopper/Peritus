import {
  BookOpen,
  CirclePlay,
  Feather,
  File,
  FileText,
  FileType,
  FlaskConical,
  Globe,
  Library,
  MessagesSquare,
  Upload,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/cn'
import { sourceKindId, type SourceKindId } from '@/lib/source-kind'

/**
 * What a source is, as a picture.
 *
 * A list of forty titles reads as one grey block; the kind is the first thing a
 * reader sorts it by — is this the book itself, a paper about it, or somebody's
 * web page — and a word in the fourth column is the slowest way to say it. One
 * icon per *kind* (`lib/source-kind.ts`), never per fetcher, and never a hue:
 * colour here is status (web/AGENTS.md, "Colour").
 */
const ICON: Record<SourceKindId, LucideIcon> = {
  paper: FileText,
  preprint: FlaskConical,
  encyclopedia: Library,
  web: Globe,
  discussion: MessagesSquare,
  video: CirclePlay,
  book: BookOpen,
  pdf: FileType,
  expert: Feather,
  upload: Upload,
  other: File,
}

export function KindIcon({
  type,
  kind,
  className,
}: {
  /** The fetcher key (`source_type`, or a map source's `kind`). */
  type?: string | null
  /** Or the kind itself, where the caller has already grouped by it. */
  kind?: SourceKindId
  className?: string
}) {
  // Decorative everywhere it is used: the kind is always also said in words,
  // beside it or in the row's accessible name.
  const Icon = ICON[kind ?? sourceKindId(type)]
  return <Icon aria-hidden="true" className={cn('size-3.5 shrink-0', className)} />
}

// ── the map's own marks ─────────────────────────────────────────────────────

/**
 * The shapes the map draws, as DOM — for its legend, the Overview's tier rows
 * and the Flow view's ports. Kept beside the painter's rules
 * (`lib/brain/paint.ts`): a primary source is a filled rounded square, a
 * secondary one outlined, a tertiary one outlined and smaller; a missing text
 * is the same square dashed; a key concept is a large disc and a concept a
 * small one; the only hue is `--warn`, on a concept judged to be in dispute.
 */
export type MapMark =
  'primary' | 'secondary' | 'tertiary' | 'gap' | 'keyConcept' | 'concept' | 'disputed'

export function MarkGlyph({ mark, className }: { mark: MapMark; className?: string }) {
  return (
    <svg
      viewBox="0 0 12 12"
      aria-hidden="true"
      className={cn('size-3 shrink-0 text-fg-2', className)}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
    >
      {mark === 'primary' && (
        <rect x="1.5" y="1.5" width="9" height="9" rx="2" fill="currentColor" />
      )}
      {mark === 'secondary' && <rect x="1.5" y="1.5" width="9" height="9" rx="2" />}
      {mark === 'tertiary' && <rect x="3" y="3" width="6" height="6" rx="1.5" />}
      {mark === 'gap' && <rect x="1.5" y="1.5" width="9" height="9" rx="2" strokeDasharray="2 2" />}
      {mark === 'keyConcept' && <circle cx="6" cy="6" r="4.5" fill="currentColor" stroke="none" />}
      {mark === 'concept' && <circle cx="6" cy="6" r="2.25" fill="currentColor" stroke="none" />}
      {mark === 'disputed' && (
        <>
          <circle cx="6" cy="6" r="4.5" className="text-warn" />
          <circle cx="6" cy="6" r="1.75" fill="currentColor" stroke="none" className="text-warn" />
        </>
      )}
    </svg>
  )
}

/** A source's tier as the map's mark; an unclassified source reads as secondary. */
export function tierMark(tier: string | null | undefined): MapMark {
  return tier === 'primary' ? 'primary' : tier === 'tertiary' ? 'tertiary' : 'secondary'
}
