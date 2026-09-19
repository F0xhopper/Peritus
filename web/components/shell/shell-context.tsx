'use client'

import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react'

import { SIDEBAR_COOKIE, SIDEBAR_COOKIE_ATTRS } from '@/lib/shell-cookie'

/**
 * The shell's open/closed state, shared between the top bar (which has the menu
 * and search buttons) and the layout (which renders the drawer, the context
 * panel and the palette).
 *
 * A context rather than props because the top bar is rendered *by each page* —
 * every page owns its own title and its one action — while the surfaces those
 * buttons open live in the layout above it. Threading callbacks down through
 * every page for this would mean every page taking three props it does not
 * otherwise care about.
 */

export interface ShellState {
  navOpen: boolean
  openNav: () => void
  closeNav: () => void
  setNavOpen: (open: boolean) => void
  /**
   * The menu button, so the drawer can hand focus back to it on close.
   *
   * Base UI returns focus to its own `Drawer.Trigger` automatically, but this
   * drawer is opened from a button in a *different* subtree — the top bar each
   * page renders — so there is nothing for it to return to unless the element
   * is named. Without this, dismissing the drawer with Escape drops focus to
   * the document and a keyboard user restarts from the top of the page.
   */
  navTriggerRef: React.RefObject<HTMLButtonElement | null>

  /** The right panel. Inline at `xl`, an overlay at `lg`, a sheet below. */
  contextOpen: boolean
  openContext: () => void
  closeContext: () => void
  setContextOpen: (open: boolean) => void

  paletteOpen: boolean
  openPalette: () => void
  setPaletteOpen: (open: boolean) => void

  /**
   * The expert sidebar, folded away at `lg` and up (`⌘\`).
   *
   * Kept in a **cookie**, not `localStorage`: the layout is server-rendered and
   * a preference the server cannot read would paint an expanded column for one
   * frame on every load for anyone who collapsed it — and this shell decides
   * layout in CSS at first paint, never in JavaScript afterwards.
   */
  sidebarCollapsed: boolean
  toggleSidebar: () => void

  /**
   * The expert the open chat belongs to, published by the chat page.
   *
   * A `/chats/[id]` URL does not name its expert, and the layout's recents are
   * only the latest twenty — so a chat created a moment ago, or an old one,
   * resolved to no expert and the shell fell back to Home around it.
   */
  chatExpert: { chatId: string; slug: string } | null
  setChatExpert: React.Dispatch<React.SetStateAction<{ chatId: string; slug: string } | null>>
}

const ShellContext = createContext<ShellState | null>(null)

export function ShellProvider({
  children,
  sidebarCollapsed: initialCollapsed = false,
}: {
  children: React.ReactNode
  /** Read from the cookie by the layout, so the first paint is already right. */
  sidebarCollapsed?: boolean
}) {
  const [navOpen, setNavOpen] = useState(false)
  const [contextOpen, setContextOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(initialCollapsed)
  const [chatExpert, setChatExpert] = useState<ShellState['chatExpert']>(null)
  const navTriggerRef = useRef<HTMLButtonElement | null>(null)

  const toggleSidebar = useCallback(() => {
    setSidebarCollapsed((collapsed) => {
      const next = !collapsed
      try {
        document.cookie = `${SIDEBAR_COOKIE}=${next ? 'collapsed' : 'open'};${SIDEBAR_COOKIE_ATTRS}`
      } catch {
        // Cookies blocked: the choice still applies for this session.
      }
      return next
    })
  }, [])

  const value = useMemo<ShellState>(
    () => ({
      navOpen,
      openNav: () => setNavOpen(true),
      closeNav: () => setNavOpen(false),
      setNavOpen,
      navTriggerRef,
      contextOpen,
      openContext: () => setContextOpen(true),
      closeContext: () => setContextOpen(false),
      setContextOpen,
      paletteOpen,
      openPalette: () => setPaletteOpen(true),
      setPaletteOpen,
      sidebarCollapsed,
      toggleSidebar,
      chatExpert,
      setChatExpert,
    }),
    [navOpen, contextOpen, paletteOpen, sidebarCollapsed, toggleSidebar, chatExpert]
  )

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>
}

export function useShell(): ShellState {
  const context = useContext(ShellContext)
  if (!context) {
    throw new Error('useShell must be used inside the (app) layout’s ShellProvider')
  }
  return context
}

/**
 * The context panel's content, published by a page and consumed by the layout.
 *
 * The panel is one region that appears in three different forms depending on
 * width, and a page must not know which — so a page hands over *content* and
 * the layout decides whether that content is an inline `<aside>`, an overlay,
 * or a bottom sheet.
 */
export interface ContextPanelContent {
  /**
   * Which mounted `ContextSlot` published this. The panel's "closed" state
   * belongs to one publisher: closing a source's panel on Knowledge must not
   * keep the build page's Cost panel shut an hour later.
   */
  owner: number
  title: string
  /** Called when the reader closes the panel — clear the selection behind it. */
  onClose?: () => void
  /** `[0.4, 0.92]` on the graph, so the canvas stays usable. */
  snapPoints?: number[]
  node: React.ReactNode
}

const ContextSlotContext = createContext<{
  content: ContextPanelContent | null
  publish: (content: ContextPanelContent | null) => void
} | null>(null)

export function ContextSlotProvider({ children }: { children: React.ReactNode }) {
  const [content, setContent] = useState<ContextPanelContent | null>(null)
  const publish = useCallback((next: ContextPanelContent | null) => setContent(next), [])
  const value = useMemo(() => ({ content, publish }), [content, publish])
  return <ContextSlotContext.Provider value={value}>{children}</ContextSlotContext.Provider>
}

export function useContextSlot() {
  const context = useContext(ContextSlotContext)
  if (!context) throw new Error('useContextSlot must be used inside the (app) layout')
  return context
}
