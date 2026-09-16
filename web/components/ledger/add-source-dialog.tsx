'use client'

import { FileText, Link2, Upload } from 'lucide-react'
import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input, Label, Textarea } from '@/components/ui/input'
import { Notice } from '@/components/ui/notice'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'

/**
 * Add a source the search could not find: a book in copyright, private notes,
 * a paper behind a login, a web page.
 *
 * Uploads go through `XMLHttpRequest` rather than `fetch`, for one reason:
 * upload progress. `fetch` still has no way to observe request-body progress
 * in any shipping browser, and a 20 MB PDF on a phone connection with a
 * spinner and no bar is indistinguishable from a hang.
 *
 * Ingest is durable — the payload is stored and a worker does the work — so the
 * dialog closes as soon as the job is queued and the page waits for the
 * `source_ingested` event on the build stream rather than holding the dialog
 * open.
 */
const MAX_BYTES = 20 * 1024 * 1024
const ACCEPT = 'application/pdf,.pdf,.txt,.md,.markdown,text/plain,text/markdown'

type Tab = 'file' | 'text' | 'url'

export function AddSourceDialog({
  slug,
  open,
  onOpenChange,
  onQueued,
}: {
  slug: string
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called with the job id to tail once the ingest is queued. */
  onQueued: (jobId: number, title: string) => void
}) {
  const [tab, setTab] = useState<Tab>('file')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [url, setUrl] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const reset = () => {
    setFile(null)
    setTitle('')
    setText('')
    setUrl('')
    setProgress(null)
    setError(null)
  }

  const queued = (jobId: number, name: string) => {
    onQueued(jobId, name)
    onOpenChange(false)
    reset()
    toast.success(`Reading ${name}…`)
  }

  const takeFile = (candidate: File | null) => {
    setError(null)
    if (!candidate) return
    if (candidate.size === 0) {
      setError('That file is empty.')
      return
    }
    if (candidate.size > MAX_BYTES) {
      setError(`That file is ${formatBytes(candidate.size)} — the limit is 20 MB.`)
      return
    }
    setFile(candidate)
    if (!title) setTitle(candidate.name.replace(/\.[^.]+$/, ''))
  }

  const uploadFile = () => {
    if (!file) return
    setBusy(true)
    setError(null)
    setProgress(0)

    const form = new FormData()
    form.set('file', file, file.name)
    if (title.trim()) form.set('title', title.trim())

    const request = new XMLHttpRequest()
    request.open('POST', `/api/experts/${encodeURIComponent(slug)}/sources/upload`)
    // The BFF's own CSRF check reads this; `XMLHttpRequest` does not set
    // `Sec-Fetch-Site` for us in every browser, and `Origin` is enough.
    request.upload.addEventListener('progress', (event) => {
      if (event.lengthComputable) setProgress(event.loaded / event.total)
    })
    request.addEventListener('load', () => {
      setBusy(false)
      setProgress(null)
      try {
        const body = JSON.parse(request.responseText) as {
          job_id?: number
          title?: string
          detail?: unknown
        }
        if (request.status >= 200 && request.status < 300 && typeof body.job_id === 'number') {
          queued(body.job_id, body.title ?? file.name)
        } else {
          setError(
            typeof body.detail === 'string' ? body.detail : `Upload failed (${request.status}).`
          )
        }
      } catch {
        setError(`Upload failed (${request.status}).`)
      }
    })
    request.addEventListener('error', () => {
      setBusy(false)
      setProgress(null)
      setError('The upload could not reach Peritus.')
    })
    request.send(form)
  }

  const submitText = async () => {
    const body = text.trim()
    if (!body) return
    setBusy(true)
    setError(null)
    try {
      // Text goes as a file upload too: the API's text branch is the same
      // endpoint, and a Blob keeps one code path on the server.
      const blob = new File([body], `${(title.trim() || 'Pasted note').slice(0, 60)}.md`, {
        type: 'text/markdown',
      })
      const form = new FormData()
      form.set('file', blob)
      if (title.trim()) form.set('title', title.trim())
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/sources/upload`, {
        method: 'POST',
        body: form,
      })
      const payload = (await res.json().catch(() => null)) as {
        job_id?: number
        title?: string
        detail?: unknown
      } | null
      if (!res.ok || typeof payload?.job_id !== 'number') {
        setError(
          typeof payload?.detail === 'string'
            ? payload.detail
            : `Could not save that (${res.status}).`
        )
        return
      }
      queued(payload.job_id, payload.title ?? 'Pasted note')
    } catch {
      setError('Could not reach Peritus.')
    } finally {
      setBusy(false)
    }
  }

  const submitUrl = async () => {
    const trimmed = url.trim()
    if (!trimmed) return
    setBusy(true)
    setError(null)
    try {
      const res = await fetch(`/api/experts/${encodeURIComponent(slug)}/sources/url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: trimmed, title: title.trim() || undefined }),
      })
      const payload = (await res.json().catch(() => null)) as {
        job_id?: number
        title?: string
        detail?: unknown
      } | null
      if (!res.ok || typeof payload?.job_id !== 'number') {
        setError(
          typeof payload?.detail === 'string'
            ? payload.detail
            : `Could not add that URL (${res.status}).`
        )
        return
      }
      queued(payload.job_id, payload.title ?? trimmed)
    } catch {
      setError('Could not reach Peritus.')
    } finally {
      setBusy(false)
    }
  }

  const submit = () => {
    if (tab === 'file') uploadFile()
    else if (tab === 'text') void submitText()
    else void submitUrl()
  }

  const canSubmit =
    !busy &&
    ((tab === 'file' && file) || (tab === 'text' && text.trim()) || (tab === 'url' && url.trim()))

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next)
        if (!next) reset()
      }}
      title="Add a source"
      description="Discovery finds what is publicly indexable. This is for everything else."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!canSubmit}
            onClick={submit}
            minWidth={92}
          >
            Add
          </Button>
        </>
      }
    >
      <div role="tablist" aria-label="Source kind" className="flex gap-0.5 rounded-row bg-bg p-0.5">
        {(
          [
            { id: 'file', label: 'PDF or file', icon: Upload },
            { id: 'text', label: 'Text', icon: FileText },
            { id: 'url', label: 'URL', icon: Link2 },
          ] as const
        ).map((option) => (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={tab === option.id}
            onClick={() => {
              setTab(option.id)
              setError(null)
            }}
            className={cn(
              'inline-flex h-(--icon-btn-sm) flex-1 items-center justify-center gap-1.5 rounded-[6px] text-xs',
              'transition-colors duration-(--dur-1)',
              tab === option.id ? 'bg-raised text-fg' : 'text-fg-3 hover:text-fg-2'
            )}
          >
            <option.icon className="size-3.5" />
            {option.label}
          </button>
        ))}
      </div>

      <div className="mt-3 space-y-3">
        {tab === 'file' && (
          <>
            <div
              onDragOver={(event) => {
                event.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                takeFile(event.dataTransfer.files[0] ?? null)
              }}
              className={cn(
                'rounded-card border border-dashed p-4 text-center',
                'transition-colors duration-(--dur-1)',
                dragging ? 'border-expert bg-expert-soft' : 'border-border'
              )}
            >
              <Upload className="mx-auto size-5 text-fg-4" aria-hidden="true" />
              <p className="mt-2 text-sm text-fg-2">
                {file ? file.name : 'Drop a PDF, .txt or .md here'}
              </p>
              <p className="mt-0.5 text-xs text-fg-3">
                {file ? formatBytes(file.size) : 'Up to 20 MB. Scanned PDFs are OCR’d.'}
              </p>
              {/* The file input is the real control; the drop zone is the
                  affordance around it. `accept` is what opens Files on iOS
                  rather than only the photo library. */}
              <input
                ref={fileInput}
                type="file"
                accept={ACCEPT}
                onChange={(event) => takeFile(event.target.files?.[0] ?? null)}
                className="sr-only"
                id="source-file"
              />
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => fileInput.current?.click()}
              >
                Choose a file
              </Button>
            </div>

            {progress !== null && (
              <div>
                <div className="h-1 overflow-hidden rounded-full bg-raised">
                  <div
                    style={{ transform: `scaleX(${progress})` }}
                    className="h-full w-full origin-left rounded-full bg-expert transition-transform duration-100"
                  />
                </div>
                <p className="mt-1 text-xs text-fg-3">{Math.round(progress * 100)}% uploaded</p>
              </div>
            )}
          </>
        )}

        {tab === 'text' && (
          <div>
            <Label htmlFor="source-text">Text or Markdown</Label>
            <Textarea
              id="source-text"
              rows={6}
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="Paste the passage, note or transcript…"
              className="mt-1.5"
            />
          </div>
        )}

        {tab === 'url' && (
          <div>
            <Label htmlFor="source-url">Page address</Label>
            <Input
              id="source-url"
              type="url"
              inputMode="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://…"
              className="mt-1.5"
            />
            <p className="mt-1 text-xs text-fg-3">
              Peritus fetches the page itself, so a slow site will not hold this open.
            </p>
          </div>
        )}

        <div>
          <Label htmlFor="source-title">Title (optional)</Label>
          <Input
            id="source-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="How it should appear in Sources"
            maxLength={300}
            className="mt-1.5"
          />
        </div>

        {error && <Notice tone="bad">{error}</Notice>}
      </div>
    </Dialog>
  )
}
