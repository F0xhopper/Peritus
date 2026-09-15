# Real-device checklist

**Status: not yet signed off.** Every line here is something the emulated
Playwright projects cannot prove. They run WebKit and Chromium on a desktop
kernel with a fake viewport: no software keyboard, no browser chrome that
collapses on scroll, no gesture navigation, no safe-area cutout, no Split View.
Phase 9 of `docs/plans/web-implementation.md` is done only when a person has
walked this on hardware and initialled it.

How to run it: build and serve the app against a real API (`npx next build && npx next start`,
with `PERITUS_API_URL` pointing at a dev API and `NEXT_PUBLIC_APP_URL` at the
address the phone will use — a LAN IP or a tunnel, not `localhost`). Google
sign-in needs that same origin in the Supabase redirect allowlist, so use the
tunnel URL for the whole pass rather than switching halfway.

## iPhone, Safari

- [ ] **Safe areas.** In landscape, and with the home indicator: the composer,
      the sticky Build footer on `/experts/new`, and the bottom sheet's grabber
      all clear the inset. Nothing sits under the indicator.
- [ ] **Keyboard.** Focusing the composer on a chat lifts it above the keyboard
      and the last message stays visible (`useVisualViewport` writes
      `--vv-offset`; Safari resizes the visual viewport only). The Build button
      on `/experts/new` is still reachable with the keyboard up.
- [ ] **No zoom on focus.** Tapping any input does not scale the page — every
      field is at least 16px on a coarse pointer.
- [ ] **`100dvh` while the toolbar collapses.** Scroll a long ledger, let the
      toolbar shrink, then open the nav drawer: the drawer is full height and
      the shell has not gained a scrollbar.
- [ ] **Pull-to-refresh does not fight the drawer.** Swiping down inside the nav
      drawer or a bottom sheet scrolls that surface (or dismisses the sheet); it
      does not reload the page. `overscroll-contain` is doing the work.
- [ ] **The graph canvas.** One finger pans, two pinch, and the page behind it
      does not scroll (`touch-action: pan-y` only where intended).
- [ ] **Reduced motion** (Settings → Accessibility → Motion): sheets appear
      without sliding, the rail's active bar jumps, the landing hero shows the
      finished log, and every interaction still works.
- [ ] **Google sign-in.** The full round trip in Safari, including the return
      from `accounts.google.com` to `/api/auth/callback`, lands signed in — the
      PKCE cookie survives the cross-site return (`SameSite=Lax` on a top-level
      GET).

## Android, Chrome

- [ ] **Keyboard resize.** `interactiveWidget: 'resizes-content'` shrinks the
      layout viewport: the composer sits on the keyboard and the transcript
      keeps its scroll position.
- [ ] **The back gesture closes the drawer** rather than leaving the app, and a
      second back leaves the page. Same for the bottom sheet and the palette.
- [ ] **The address bar collapsing** does not leave a gap under the composer.
- [ ] **Dark and light** follow the system setting, and the in-app theme toggle
      overrides it in both directions.

## iPad, Safari

- [ ] **Landscape overlay panel.** At `lg` the context panel is an overlay: it
      dims the page, traps focus, and Escape closes it back onto the trigger.
- [ ] **Split View at 50%** and at the narrow third: the shell drops to the
      phone layout without horizontal overflow, and the rail hides rather than
      squeezing.
- [ ] **External keyboard.** `⌘K` opens the palette, `Escape` closes every
      overlay, `Tab` order through the ledger is the visual order, and the
      focus ring is visible on a dark surface.
- [ ] **Tap targets with a stylus and a thumb.** The rail, the table's sort
      headers and the build log's group rows are all 44px on this device — this
      is the class of bug the width-only `md:` breakpoint caused.

## What to record

For each failure: the device, the OS version, the page, and a screen recording.
A layout bug on a real phone is usually a token or a breakpoint, not a page —
fix it in `app/globals.css` or in the component's variant, and add the assertion
to `e2e/helpers.ts` if it is something an emulated run *could* have caught.
