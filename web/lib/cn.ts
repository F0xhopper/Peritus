import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

/**
 * tailwind-merge resolves conflicts by class *group*, and it only knows
 * Tailwind's own font sizes. This project's — `--text-label`, `--text-md`,
 * `--text-title`, `--text-stat`, `--text-hero` in `globals.css` — looked to it
 * like colours, so `cn('text-label uppercase', 'text-fg-3')` kept the colour
 * and **silently dropped the size**: section labels, table headers and the stat
 * tiles' values all rendered at whatever size they inherited. Naming them here
 * puts them in the font-size group, where a colour no longer displaces them.
 *
 * A size token added to `globals.css` must be added here too.
 */
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ['label', 'md', 'title', 'stat', 'hero'] } },
})

/** Conditional classes with later Tailwind utilities winning over earlier ones. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
