import type { ExpertPicture } from '@/lib/api/types'
import { cn } from '@/lib/cn'

/**
 * Who made the picture, and under what licence.
 *
 * This is not a courtesy. CC BY and CC BY-SA — most of what Commons offers —
 * *oblige* attribution wherever the work is shown, and the whole reason the
 * picture is a found image with recorded provenance rather than a generated one
 * is that its origin can be stated. So the credit is part of the feature, not a
 * decoration on it.
 *
 * It renders where the picture is the identity of a page — the Overview header,
 * expert settings — and deliberately not in the rail, the sidebar or a chat
 * message. A 20px tile in a list is a navigational mark, the credit would be
 * longer than the row it sits in, and the page one click away carries it.
 *
 * Nothing renders for a public-domain or CC0 picture (`attribution_required`
 * is false): naming a 2,300-year-old bust's "artist" is noise, and the file
 * page is still reachable from the Overview's provenance if anyone wants it.
 */
export function PictureCredit({
  picture,
  className,
}: {
  picture: ExpertPicture
  className?: string
}) {
  if (!picture.attribution_required) return null

  const artist = picture.artist?.trim()
  const title = picture.title?.trim()

  return (
    <p className={cn('text-xs text-fg-3', className)}>
      Picture:{' '}
      <a
        href={picture.file_page_url}
        target="_blank"
        rel="noopener noreferrer"
        className="underline decoration-fg-4 underline-offset-2 transition-colors duration-(--dur-1) hover:text-fg-2"
      >
        {title || 'source file'}
      </a>
      {artist && <> · {artist}</>} ·{' '}
      {picture.license_url ? (
        <a
          href={picture.license_url}
          target="_blank"
          rel="noopener noreferrer"
          className="underline decoration-fg-4 underline-offset-2 transition-colors duration-(--dur-1) hover:text-fg-2"
        >
          {picture.license}
        </a>
      ) : (
        picture.license
      )}
    </p>
  )
}
