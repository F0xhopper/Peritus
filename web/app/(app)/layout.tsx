import { ViewTransition } from 'react'

import { CommandPalette } from '@/components/shell/command-palette'
import { ContextPanel } from '@/components/shell/context-panel'
import { ExpertSidebar } from '@/components/shell/expert-sidebar'
import { NavDrawer } from '@/components/shell/nav-drawer'
import { Rail } from '@/components/shell/rail'
import { ContextSlotProvider, ShellProvider } from '@/components/shell/shell-context'
import { ShellBody } from '@/components/shell/shell-body'
import { TooltipProvider } from '@/components/ui/tooltip'
import { getBilling, getConversations, getExperts, getMe } from '@/lib/api/data'

/**
 * The app shell.
 *
 * One CSS grid at `h-dvh`: `[56px 260px 1fr auto]` at `xl`, dropping a column
 * per tier down to a single column below `md`. Each column is its own scroll
 * container; the window itself never scrolls inside the app, only on the
 * marketing pages.
 *
 * The last column is **`auto`, not `360px`**. A fixed track reserved the panel's
 * width whether or not a page had published anything into it, so on a wide
 * screen the chat and Home pages ran with 360px of dead space pinned to the
 * right edge and their content pushed off centre. `ContextPanel` renders
 * nothing when the slot is empty, and an `auto` track with nothing in it is
 * zero wide; the panel's own `w-context` gives it its size when it is there.
 *
 * **Layout is decided by CSS, never by JavaScript.** Both forms of every region
 * are in this HTML and toggled with `hidden md:flex`, so the server render is
 * correct at every width and there is no post-hydration jump. `useMediaQuery`
 * decides *behaviour* — drawer or inline — and is never read to choose what to
 * render at first paint.
 *
 * The four fetches here are the shell's own data, shared by every page beneath
 * it, so navigating inside the app re-renders the centre column only.
 */
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // `getExperts` first and alone: it is the call that redirects to `/login`
  // when the session is dead, and firing all four at a dead session would race
  // four redirects against each other.
  const experts = await getExperts()
  const [conversations, credits, me] = await Promise.all([
    getConversations(20),
    // Billing is not load-bearing for the shell. If it fails, the credit rows
    // simply are not rendered, rather than the whole app failing to paint.
    getBilling().catch(() => null),
    getMe().catch(() => null),
  ])

  return (
    <ShellProvider>
      <ContextSlotProvider>
        <TooltipProvider>
          {/* Sets `data-shell="app"` on <body>, which is what stops the window
              scrolling while the app is mounted. */}
          <ShellBody />

          <div className="grid h-dvh grid-cols-1 overflow-hidden md:grid-cols-[56px_minmax(0,1fr)] lg:grid-cols-[56px_260px_minmax(0,1fr)] xl:grid-cols-[56px_260px_minmax(0,1fr)_auto]">
            {/* Rail and sidebar are one navigation region on one surface, with
                no rule between them and none against the content. Depth is the
                surface step (`--panel` beside `--bg`), which is the design's
                own rule and how the references do it — a vertical hairline down
                the whole window is the loudest line in a layout that otherwise
                has almost none. */}
            <Rail
              experts={experts}
              conversations={conversations}
              me={me}
              className="hidden md:flex"
            />

            <ExpertSidebar
              experts={experts}
              conversations={conversations}
              credits={credits}
              showSearch
              className="scroll-col hidden lg:flex"
            />

            <main className="flex min-h-0 min-w-0 flex-col bg-bg">
              {/* React's ViewTransition crossfades the centre column on
                  navigation while the rail and sidebar stay put. With no
                  browser support the swap is instant, which is the intended
                  fallback — the skeletons match, so nothing jumps. */}
              <ViewTransition default="vt-fade">{children}</ViewTransition>
            </main>

            <ContextPanel />
          </div>

          <NavDrawer
            experts={experts}
            conversations={conversations}
            credits={credits}
            me={me}
          />
          <CommandPalette experts={experts} conversations={conversations} />
        </TooltipProvider>
      </ContextSlotProvider>
    </ShellProvider>
  )
}
