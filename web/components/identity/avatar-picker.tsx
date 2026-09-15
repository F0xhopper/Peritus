'use client'

import { Dice5, Pencil, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { toast } from 'sonner'

import { Avatar } from '@/components/identity/avatar'
import { PictureCredit } from '@/components/identity/picture-credit'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { cn } from '@/lib/cn'
import {
  AVATAR_STYLES,
  randomSeed,
  resolveRecipe,
  type AvatarRecipe,
} from '@/lib/avatar'
import type { ExpertSummary } from '@/lib/api/types'

/**
 * Change an expert's avatar.
 *
 * Nothing here is uploaded. An expert either shows the **found picture** of its
 * subject — a real, licensed image the build found on Wikimedia and the server
 * stored, credited below the preview — or a *generated* drawing from a seed.
 * There is no colour choice: every expert is monochrome. A user still cannot
 * put an image of anything they like beside answers that cite real sources.
 *
 * Three details that make it feel finished rather than merely functional:
 *
 * **Everything previews live.** The recipe is local state and the preview is
 * the same `Avatar` the rail renders, so what is on screen is exactly what will
 * be saved. Nothing is written until Save.
 *
 * **Reset means "back to the default", and the default is now the picture.**
 * A pinned recipe overrides everything below it, so there has to be a way back
 * — which is a `null` avatar, not another recipe. Where a picture exists, that
 * is what null resolves to.
 *
 * **Removing the picture is a separate action from choosing a drawing.** They
 * look interchangeable and are not: picking Monogram writes a recipe that Reset
 * would undo, bringing the picture straight back. Remove deletes the picture
 * itself, and is the only way to say "not this, and not any".
 */
export function AvatarPicker({
  expert,
  children,
}: {
  expert: Pick<ExpertSummary, 'name' | 'persona_name' | 'topic' | 'avatar' | 'picture'>
  /** The avatar itself, wrapped so the whole thing is the trigger. */
  children: React.ReactNode
}) {
  const router = useRouter()
  const [open, setOpen] = useState(false)
  const [recipe, setRecipe] = useState<AvatarRecipe>(() => resolveRecipe(expert))
  const [saving, setSaving] = useState(false)
  // Separate from `saving`: these two hit different endpoints and must not put
  // the Save button into a loading state it will never come out of.
  const [pictureBusy, setPictureBusy] = useState<'refresh' | 'remove' | null>(null)
  const picture = expert.picture

  // Reopening after a cancel must not keep the abandoned draft. Adjusted
  // during render rather than in an effect: an effect would paint the stale
  // draft for one frame first, and React re-runs this render immediately
  // without committing the discarded one.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setRecipe(resolveRecipe(expert))
  }

  const save = async (next: AvatarRecipe | null) => {
    setSaving(true)
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(expert.name)}/avatar`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          avatar: next
            ? // The monogram needs no seed of its own — it reads the initials
              // from the persona name.
              { style: next.style, seed: next.seed, hue: null }
            : null,
        }),
      })
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
        throw new Error(typeof body?.detail === 'string' ? body.detail : 'Save failed')
      }
      toast.success(next ? 'Avatar updated' : 'Avatar reset to the generated default')
      setOpen(false)
      router.refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save that avatar.')
    } finally {
      setSaving(false)
    }
  }

  /** The two picture actions. Both write server-side and then re-render. */
  const pictureAction = async (
    kind: 'refresh' | 'remove',
    path: string,
    method: string,
    success: string,
  ) => {
    setPictureBusy(kind)
    try {
      const res = await fetch(path, { method })
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: unknown } | null
        throw new Error(
          typeof body?.detail === 'string' ? body.detail : 'That did not work.',
        )
      }
      toast.success(success)
      setOpen(false)
      router.refresh()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'That did not work.')
    } finally {
      setPictureBusy(null)
    }
  }

  const base = `/api/experts/${encodeURIComponent(expert.name)}/picture`

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Change avatar"
        className={cn(
          'group relative rounded-card',
          'transition-opacity duration-(--dur-1) hover:opacity-80',
        )}
      >
        {children}
        <span
          aria-hidden="true"
          className={cn(
            'pointer-events-none absolute -right-1 -bottom-1 grid size-4 place-items-center',
            'rounded-full bg-raised text-fg-3 ring-1 ring-border',
            'opacity-0 transition-opacity duration-(--dur-1) group-hover:opacity-100',
            '[@media(hover:none)]:opacity-100',
          )}
        >
          <Pencil className="size-2.5" />
        </span>
      </button>

      <Dialog
        open={open}
        onOpenChange={setOpen}
        title="Avatar"
        description={
          picture
            ? 'A found picture of the subject, or a generated drawing. Never an upload.'
            : 'Generated, never uploaded — so it is the same on every device and costs nothing to store.'
        }
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => void save(null)}
              disabled={saving || !expert.avatar}
            >
              <RotateCcw className="size-3.5" />
              Reset
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              loading={saving}
              onClick={() => void save(recipe)}
              minWidth={84}
            >
              Save
            </Button>
          </>
        }
      >
        {picture && (
          <div className="mb-5 rounded-card bg-raised p-3">
            <div className="flex items-start gap-3">
              <Avatar expert={expert} recipe={{ ...recipe, style: 'picture' }} size={48} />
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => setRecipe((r) => ({ ...r, style: 'picture' }))}
                  aria-pressed={recipe.style === 'picture'}
                  className={cn(
                    'text-sm transition-colors duration-(--dur-1)',
                    recipe.style === 'picture' ? 'text-fg' : 'text-fg-2 hover:text-fg',
                  )}
                >
                  Picture{picture.title ? ` — ${picture.title}` : ''}
                </button>
                <PictureCredit picture={picture} className="mt-0.5" />
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    loading={pictureBusy === 'refresh'}
                    disabled={pictureBusy !== null || saving}
                    onClick={() =>
                      void pictureAction(
                        'refresh',
                        `${base}/refresh`,
                        'POST',
                        'Found another picture',
                      )
                    }
                  >
                    <RefreshCw className="size-3.5" />
                    Find another
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    loading={pictureBusy === 'remove'}
                    disabled={pictureBusy !== null || saving}
                    onClick={() =>
                      void pictureAction('remove', base, 'DELETE', 'Picture removed')
                    }
                  >
                    <Trash2 className="size-3.5" />
                    Remove
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="flex items-center gap-4">
          <Avatar expert={expert} recipe={recipe} size={64} />
          <div className="flex min-w-0 flex-1 flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRecipe((r) => ({ ...r, seed: randomSeed() }))}
            >
              <Dice5 className="size-3.5" />
              Shuffle
            </Button>
          </div>
        </div>

        <p className="mt-4 text-label tracking-[0.04em] text-fg-3 uppercase">Style</p>
        <div className="mt-1.5 grid grid-cols-3 gap-2 sm:grid-cols-6">
          {AVATAR_STYLES.map((option) => {
            const preview: AvatarRecipe = { ...recipe, style: option.style }
            const selected = recipe.style === option.style
            return (
              <button
                key={option.style}
                type="button"
                onClick={() => setRecipe(preview)}
                aria-pressed={selected}
                title={option.hint}
                className={cn(
                  'flex flex-col items-center gap-1 rounded-card border p-1.5',
                  'transition-colors duration-(--dur-1)',
                  selected ? 'border-expert bg-expert-soft' : 'border-border hover:border-fg-4',
                )}
              >
                <Avatar expert={expert} recipe={preview} size={36} />
                <span
                  className={cn(
                    'w-full truncate text-center text-xs',
                    selected ? 'text-fg' : 'text-fg-3',
                  )}
                >
                  {option.label}
                </span>
              </button>
            )
          })}
        </div>

        {!expert.avatar && (
          <p className="mt-4 text-xs text-fg-3">
            {picture
              ? 'Right now this expert shows its found picture. Saving here pins a drawing instead; Reset brings the picture back.'
              : 'Right now this avatar is derived from the persona name, so a rebuild that renames the expert changes it. Saving here pins it.'}
          </p>
        )}
      </Dialog>
    </>
  )
}
