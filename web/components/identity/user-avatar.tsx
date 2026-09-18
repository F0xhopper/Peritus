'use client'

import { useState } from 'react'

import { cn } from '@/lib/cn'

/**
 * The signed-in person: their Google profile picture when the account has one,
 * otherwise the first letter of their name or email on a neutral disc.
 *
 * A plain `<img>`, not `next/image`: the picture is already sized by Google and
 * the optimiser would fetch it server-side for nothing. `no-referrer` because
 * Google's image host refuses some requests that carry one, and the letter
 * comes back if the picture fails anyway — a revoked or expired URL should look
 * like no picture, not a broken image.
 */
export function UserAvatar({
  name,
  email,
  avatarUrl,
  size = 32,
  className,
}: {
  name?: string | null
  email?: string | null
  avatarUrl?: string | null
  size?: number
  className?: string
}) {
  const [failed, setFailed] = useState<string | null>(null)
  const initial = (name?.trim() || email || '?').slice(0, 1).toUpperCase()
  const showPicture = avatarUrl && failed !== avatarUrl

  return (
    <span
      aria-hidden="true"
      style={{ width: size, height: size }}
      className={cn(
        'grid shrink-0 place-items-center overflow-hidden rounded-full bg-raised font-medium text-fg-2',
        size >= 32 ? 'text-xs' : 'text-[10px]',
        className
      )}
    >
      {showPicture ? (
        // eslint-disable-next-line @next/next/no-img-element -- see above
        <img
          src={avatarUrl}
          alt=""
          width={size}
          height={size}
          referrerPolicy="no-referrer"
          decoding="async"
          onError={() => setFailed(avatarUrl)}
          className="size-full object-cover"
        />
      ) : (
        initial
      )}
    </span>
  )
}
