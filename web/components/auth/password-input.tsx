'use client'

import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { Input } from '@/components/ui/input'
import { cn } from '@/lib/cn'

/**
 * A password field with a show/hide toggle.
 *
 * The toggle is a real button inside the field, reachable by keyboard, with a
 * label that says what pressing it will do. Paste is never blocked, and the
 * caller sets `autoComplete` — `current-password` on sign-in,
 * `new-password` on sign-up and change — which is what makes a password
 * manager offer to fill or generate.
 */
export function PasswordInput({
  className,
  ...props
}: Omit<React.ComponentProps<'input'>, 'type'>) {
  const [visible, setVisible] = useState(false)
  return (
    <div className="relative">
      <Input
        {...props}
        type={visible ? 'text' : 'password'}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        className={cn('pr-10', className)}
      />
      <button
        type="button"
        onClick={() => setVisible((value) => !value)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        className={cn(
          'absolute inset-y-0 right-0 flex w-(--row-h) items-center justify-center rounded-r-row',
          'text-fg-3 transition-colors duration-(--dur-1) hover:text-fg',
          'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-fg'
        )}
      >
        {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}
