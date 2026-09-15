'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { displayName } from '@/lib/persona'
import type { ExpertSummary } from '@/lib/api/types'

/**
 * Deleting an expert, behind the name typed out.
 *
 * A build costs real credits and real provider spend, and the corpus — every
 * source it kept and every one it rejected — goes with it. A type-the-name
 * confirm is the right amount of friction for something that cannot be undone
 * and cannot be cheaply rebuilt.
 *
 * `Dialog` is a bottom sheet below `md`, and the confirm button sits above the
 * safe area there, so the destructive action is never under the home indicator.
 */
export function ConfirmDelete({
  expert,
  open,
  onOpenChange,
  onConfirm,
  deleting,
}: {
  expert: ExpertSummary
  open: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
  deleting: boolean
}) {
  const name = displayName(expert)
  const [typed, setTyped] = useState('')

  // Cleared on every open, so a dialog reopened after a cancel does not start
  // one keystroke from deleting something. Adjusted during render, not in an
  // effect — the field must never be briefly pre-filled on a destructive
  // dialog, not even for a frame.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setTyped('')
  }

  const matches = typed.trim().toLowerCase() === name.toLowerCase()

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Delete ${name}?`}
      description="This removes the expert, its whole source ledger, its passages and its graph. It cannot be undone, and rebuilding costs credits again."
      // Backdrop dismissal is off: a mis-tap outside a destructive dialog
      // should not be the thing that closes it.
      disablePointerDismissal
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            disabled={!matches}
            loading={deleting}
            onClick={onConfirm}
            minWidth={96}
          >
            Delete
          </Button>
        </>
      }
    >
      <label className="block text-sm text-fg-2">
        Type <span className="font-medium text-fg">{name}</span> to confirm.
        <Input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          aria-label={`Type ${name} to confirm deletion`}
          className="mt-1.5"
        />
      </label>
    </Dialog>
  )
}
