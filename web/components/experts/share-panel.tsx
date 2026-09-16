'use client'

import { Check, Copy, Link2, Share2 } from 'lucide-react'
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { Skeleton } from '@/components/ui/skeleton'
import { sharePath } from '@/lib/access'
import { plural } from '@/lib/format'
import type { ShareState } from '@/lib/api/types'
import { apiJson, apiVoid, messageFor } from '@/lib/api/client'

/**
 * An expert's share link: "anyone with the link can read and ask".
 *
 * The model is a document's link sharing, and the copy says exactly what it
 * does, because this is the one control in the product that hands an owner's
 * work to other people:
 *
 * - **Anyone with the link** sees the expert's card. Signed in, they can open
 *   its Overview, Sources and concept map, and ask it questions. They cannot
 *   change anything.
 * - **Chats stay private both ways.** Each person's chats are their own; the
 *   owner never sees a viewer's questions, and a viewer never sees the owner's.
 * - **Uploads are named before the link exists.** Answers quote passages, so a
 *   viewer can read parts of anything the owner uploaded. The count is on the
 *   response so this is said up front, not discovered later.
 * - **Resetting is revocation.** A new link, and everyone who opened the old one
 *   loses access. Stopping sharing does the same without a new link. Both are
 *   confirmed, because neither can be undone for the people it cuts off.
 */
export function SharePanel({
  slug,
  name,
  initial,
}: {
  slug: string
  name: string
  /** Server-fetched state, or undefined to fetch it on mount. */
  initial?: ShareState | null
}) {
  const [state, setState] = useState<ShareState | null>(initial ?? null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState<'enable' | 'reset' | 'disable' | null>(null)
  const [confirming, setConfirming] = useState<'reset' | 'disable' | null>(null)
  const endpoint = `/api/experts/${encodeURIComponent(slug)}/share`

  // State is only set once the response is in, never synchronously in the
  // effect that starts it.
  const load = useCallback(
    () =>
      apiJson<ShareState>(endpoint)
        .then(setState)
        .catch(() => setLoadFailed(true)),
    [endpoint]
  )

  useEffect(() => {
    // Only when the caller had nothing to hand over. No abort on unmount: a
    // Strict Mode remount would kill the first request (see web/AGENTS.md).
    if (initial === undefined) void load()
  }, [initial, load])

  const act = async (kind: 'enable' | 'reset' | 'disable') => {
    const fallback =
      kind === 'enable'
        ? 'Could not create a link.'
        : kind === 'reset'
          ? 'Could not reset the link.'
          : 'Could not turn sharing off.'
    setBusy(kind)
    try {
      const path = kind === 'reset' ? `${endpoint}/reset` : endpoint
      const method = kind === 'enable' ? 'PUT' : kind === 'reset' ? 'POST' : 'DELETE'
      if (kind === 'disable') {
        // 204: there is no state to read back, so it is applied locally.
        await apiVoid(path, { method }, fallback)
        setState((current) =>
          current
            ? { ...current, enabled: false, token: null, created_at: null, viewer_count: 0 }
            : current
        )
        toast.success('Sharing is off. The link no longer works.')
      } else {
        setState(await apiJson<ShareState>(path, { method }, fallback))
        toast.success(
          kind === 'reset' ? 'New link created. The old one no longer works.' : 'Link created'
        )
      }
      setConfirming(null)
    } catch (error) {
      toast.error(messageFor(error, fallback))
    } finally {
      setBusy(null)
    }
  }

  if (!state) {
    return loadFailed ? (
      <Notice
        tone="bad"
        action={
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              setLoadFailed(false)
              void load()
            }}
          >
            Try again
          </Button>
        }
      >
        Could not load this expert’s sharing settings.
      </Notice>
    ) : (
      <div className="space-y-2" aria-busy="true">
        <Skeleton className="h-4 w-3/4" />
        <Skeleton className="h-(--row-h) w-full" />
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      <ul className="space-y-1 text-fg-2">
        <li>
          Anyone with the link can see what {name} is. Once signed in, they can read its sources and
          concept map and ask it questions.
        </li>
        <li>They cannot rebuild, edit or delete it, or share it on.</li>
        <li>Chats stay private: you never see theirs, and they never see yours.</li>
      </ul>

      {state.uploaded_source_count > 0 && (
        <Notice
          tone="warn"
          title={`Includes ${plural(state.uploaded_source_count, 'file')} you uploaded`}
        >
          Answers quote the passages they cite, so people with the link can read parts of{' '}
          {state.uploaded_source_count === 1 ? 'it' : 'them'}. Only share what you have the right to
          share.
        </Notice>
      )}

      {state.enabled && state.token ? (
        <LinkRow token={state.token} name={name} viewers={state.viewer_count} />
      ) : (
        <Button
          variant="primary"
          loading={busy === 'enable'}
          minWidth={132}
          onClick={() => void act('enable')}
        >
          <Link2 className="size-3.5" />
          Create link
        </Button>
      )}

      {state.enabled &&
        (confirming ? (
          // Inline rather than a second dialog: this panel already lives in
          // one, and below `md` that would stack a sheet on a sheet.
          <Notice
            tone="warn"
            title={confirming === 'reset' ? 'Reset the link?' : 'Stop sharing?'}
            action={
              <>
                <Button
                  variant="danger"
                  size="sm"
                  loading={busy !== null}
                  minWidth={104}
                  onClick={() => void act(confirming)}
                >
                  {confirming === 'reset' ? 'Reset link' : 'Stop sharing'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setConfirming(null)}>
                  Cancel
                </Button>
              </>
            }
          >
            {confirming === 'reset'
              ? 'The current link stops working and everyone who opened it loses access. You get a new link to send again.'
              : 'The link stops working and everyone who opened it loses access. Their chats are kept, but they cannot ask anything new.'}
          </Notice>
        ) : (
          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="outline" size="md" onClick={() => setConfirming('reset')}>
              Reset link
            </Button>
            <Button variant="danger" size="md" onClick={() => setConfirming('disable')}>
              Stop sharing
            </Button>
          </div>
        ))}
    </div>
  )
}

const noSubscribe = () => () => {}

function LinkRow({ token, name, viewers }: { token: string; name: string; viewers: number }) {
  const [copied, setCopied] = useState(false)
  // Built from the page's own origin, so a preview deployment hands out links
  // to itself rather than to production. Read through an external store with a
  // server snapshot: the Settings page renders this on the server, where there
  // is no origin, and a value that differed at hydration would be a mismatch.
  const origin = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => ''
  )
  const canNativeShare = useSyncExternalStore(
    noSubscribe,
    () => typeof navigator.share === 'function',
    () => false
  )
  const url = `${origin}${sharePath(token)}`

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      toast.success('Link copied')
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // No clipboard permission (an embedded browser, an insecure origin):
      // select the text so a long-press or ⌘C finishes the job.
      document.getElementById('share-link-url')?.focus()
      toast.error('Could not copy. The link is selected — copy it from there.')
    }
  }

  return (
    <div>
      <label htmlFor="share-link-url" className="sr-only">
        Share link
      </label>
      <div className="flex gap-2">
        <Input
          id="share-link-url"
          readOnly
          value={url}
          onFocus={(event) => event.currentTarget.select()}
          className="min-w-0 flex-1 font-mono text-xs"
        />
        <Button
          variant="secondary"
          onClick={() => void copy()}
          minWidth={88}
          aria-label="Copy link"
        >
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </Button>
        {canNativeShare && (
          <Button
            variant="secondary"
            size="icon"
            aria-label="Share with…"
            onClick={() =>
              void navigator.share({ title: name, url }).catch(() => {
                /* dismissed */
              })
            }
            className="pointer-fine:hidden"
          >
            <Share2 className="size-4" />
          </Button>
        )}
      </div>
      <p className="mt-1.5 text-xs text-fg-3">
        {viewers > 0
          ? `${plural(viewers, 'person has', 'people have')} opened this link.`
          : 'Nobody has opened this link yet.'}
      </p>
    </div>
  )
}

/**
 * The share panel in a dialog, for the Overview's menu. Fetches when opened,
 * so an Overview render never spends a request on a menu nobody opened.
 */
export function ShareDialog({
  slug,
  name,
  open,
  onOpenChange,
}: {
  slug: string
  name: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={`Share ${name}`}>
      {open && <SharePanel slug={slug} name={name} />}
    </Dialog>
  )
}
