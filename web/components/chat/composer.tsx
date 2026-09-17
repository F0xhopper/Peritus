'use client'

import { ArrowUp, Square, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'
import { useVisualViewport } from '@/hooks/use-visual-viewport'

/**
 * The question box, pinned to the bottom of the transcript.
 *
 * Sizes itself to its content with `field-sizing: content` and a
 * `scrollHeight` fallback for browsers that lack it, up to six lines. No
 * animation on the growth: the textarea reaching its new height *is* the
 * feedback, and easing it would lag the cursor behind the caret.
 *
 * `pb-keyboard` adds the iOS keyboard inset that `useVisualViewport` measures
 * — Safari resizes the visual viewport and not the layout viewport, so without
 * it this sits behind the keyboard on every iPhone.
 */
const MAX_LINES = 6
const MAX_CHARS = 4000

export function Composer({
  onSend,
  onStop,
  streaming,
  disabled,
  disabledReason,
  placeholder,
  /** "about: <source>" — set when the composer was opened from a row or node. */
  about,
  onClearAbout,
  autoFocus,
  draft,
}: {
  onSend: (question: string) => void
  onStop: () => void
  streaming: boolean
  disabled?: boolean
  disabledReason?: React.ReactNode
  placeholder?: string
  about?: string | null
  onClearAbout?: () => void
  autoFocus?: boolean
  /** A question to put in the box — "Ask about this" from the passage panel.
   *  `id` changes on every request, so the same text can be asked for twice. */
  draft?: { text: string; id: number } | null
}) {
  const [value, setValue] = useState('')
  // Adopt a new draft during render (not in an effect), so the box never
  // paints a frame with the old text.
  const [draftId, setDraftId] = useState(draft?.id ?? null)
  if (draft && draft.id !== draftId) {
    setDraftId(draft.id)
    setValue(draft.text)
  }
  const textarea = useRef<HTMLTextAreaElement>(null)
  useVisualViewport()

  // Put the cursor at the end of an adopted draft, ready to edit or send.
  useEffect(() => {
    if (!draft) return
    const element = textarea.current
    if (!element) return
    element.focus()
    element.setSelectionRange(element.value.length, element.value.length)
  }, [draft])

  // Focus on a mouse, never on touch: `autoFocus` on a phone raises the
  // keyboard over the transcript the moment a chat opens, before the reader has
  // seen the answer they came back for.
  useEffect(() => {
    if (autoFocus && window.matchMedia('(pointer: fine)').matches) textarea.current?.focus()
  }, [autoFocus])

  // The `field-sizing` fallback. Runs on every change, but it is two reads and
  // a write on one element — cheaper than a resize observer.
  useEffect(() => {
    const element = textarea.current
    if (!element) return
    if (CSS.supports?.('field-sizing', 'content')) return
    element.style.height = 'auto'
    const lineHeight = Number.parseFloat(getComputedStyle(element).lineHeight) || 20
    element.style.height = `${Math.min(element.scrollHeight, lineHeight * MAX_LINES + 16)}px`
  }, [value])

  const send = () => {
    const trimmed = value.trim()
    if (!trimmed || disabled || streaming) return
    setValue('')
    // Reset the fallback height too, or an empty box keeps six lines of space.
    if (textarea.current) textarea.current.style.height = ''
    onSend(trimmed)
  }

  if (disabled) {
    return (
      <div className="pb-keyboard shrink-0 bg-bg px-3 pt-3 md:px-4">
        <p className="mx-auto max-w-[720px] rounded-card bg-panel px-3 py-2.5 text-sm text-fg-3 xl:mx-0 xl:ml-12">
          {disabledReason ?? 'This expert cannot answer yet.'}
        </p>
      </div>
    )
  }

  /**
   * The same 720px measure as the transcript, and no rule above it.
   *
   * Full-bleed, the box was half again as wide as the column of text it
   * belonged to, which read as two unrelated regions; and the top border was a
   * line across the widest part of the page in a layout that has almost none.
   * The surface step and the alignment are enough to say "this is where you
   * type".
   */
  return (
    <div className="pb-keyboard shrink-0 bg-bg px-3 pt-2 md:px-4">
      {/* Aligned with the transcript above it, including the `xl` gutter that
          keeps both still when the passage panel opens. */}
      <div className="mx-auto w-full max-w-[720px] xl:mx-0 xl:ml-12">
        {about && (
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="inline-flex max-w-full items-center gap-1 rounded-chip bg-expert-soft px-2 py-0.5 text-xs text-expert">
              <span className="truncate">about: {about}</span>
              {onClearAbout && (
                <button
                  type="button"
                  onClick={onClearAbout}
                  aria-label="Clear the subject"
                  className="shrink-0 opacity-70 transition-opacity hover:opacity-100"
                >
                  <X className="size-3" />
                </button>
              )}
            </span>
          </div>
        )}

        <div
          className={cn(
            'flex items-end gap-2 rounded-card border border-border bg-panel p-1.5',
            'transition-colors duration-(--dur-1)',
            'focus-within:border-fg-4'
          )}
        >
          <textarea
            ref={textarea}
            value={value}
            onChange={(event) => setValue(event.target.value.slice(0, MAX_CHARS))}
            onKeyDown={(event) => {
              // Enter sends only where there is a real keyboard. On a phone
              // Enter is the newline and the send button is the only submit.
              if (
                event.key === 'Enter' &&
                !event.shiftKey &&
                window.matchMedia('(hover: hover)').matches
              ) {
                event.preventDefault()
                send()
              }
            }}
            rows={1}
            placeholder={placeholder ?? 'Ask a question…'}
            aria-label="Your question"
            className={cn(
              'min-h-[2rem] w-full min-w-0 flex-1 resize-none bg-transparent px-1.5 py-1',
              'text-base leading-relaxed text-fg placeholder:text-fg-3 focus:outline-none md:text-base',
              '[field-sizing:content]'
            )}
            style={{ maxHeight: `${MAX_LINES * 1.6}em` }}
          />
          {/* Stop replaces Send in place — a crossfade, not two buttons. */}
          {streaming ? (
            <Button variant="secondary" size="icon" onClick={onStop} aria-label="Stop">
              <Square className="size-3.5" />
            </Button>
          ) : (
            <Button
              variant="primary"
              size="icon"
              onClick={send}
              disabled={!value.trim()}
              aria-label="Send"
            >
              <ArrowUp className="size-4" />
            </Button>
          )}
        </div>

        {/* The same hint the Overview's composer carries, and the half of it
            nobody guesses: Enter sends, so a multi-line question needs
            Shift+Enter. Fine pointers only — on a phone Enter *is* the
            newline and there is nothing to say. */}
        <p className="mt-1 hidden text-right text-xs text-fg-3 pointer-fine:block">
          {value.length > MAX_CHARS * 0.9
            ? `${value.length} / ${MAX_CHARS}`
            : 'Enter to send · Shift+Enter for a new line'}
        </p>
      </div>
    </div>
  )
}
