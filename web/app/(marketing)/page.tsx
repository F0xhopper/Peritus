import {
  ArrowRight,
  ArrowUp,
  ArrowUpRight,
  Check,
  FileOutput,
  FileSearch,
  Gauge,
  Layers,
  ListChecks,
  Network,
  Plus,
  Ruler,
  ScanSearch,
  ScrollText,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'

import { BuildLogReplay } from '@/components/marketing/build-log-replay'
import { Faq } from '@/components/marketing/faq'
import { RecordedTable } from '@/components/marketing/recorded-table'
import { CitationWireframe, LedgerWireframe, MapWireframe } from '@/components/marketing/wireframes'
import { DEPTH } from '@/lib/build/copy'
import { cn } from '@/lib/cn'
import type { ExpertTier } from '@/lib/api/types'

export const metadata = {
  // `absolute`: the root template would otherwise append " · Peritus" to a
  // title that already starts with the name.
  title: { absolute: 'Peritus — experts built from the evidence, with the receipts' },
}

/**
 * The landing page.
 *
 * It has the shape of a product site — a lit hero, a product window, feature
 * cards, a tiers row, an FAQ, a closing call — and none of the usual furniture
 * that shape comes with. **Nothing here is invented**: no customer logos, no
 * "trusted by", no testimonial, no accuracy figure, no price. The strip under
 * the hero names what is *searched*, the tiers are depths rather than plans
 * (there is no checkout, and the page says so), and the one piece of product
 * shown with content in it is a build log recorded from a real build. The cards
 * are line drawings for the same reason — see `wireframes.tsx`.
 *
 * All of the light is CSS gradients (`.mk-*` in globals.css): no images, no
 * blur filters, nothing for the CSP to allow and nothing that costs a frame.
 * The page is server-rendered except the log replay.
 */

const CLAIMS = [
  'Eleven sources, searched at once.',
  'Every candidate scored against a written, versioned rubric.',
  'Every rejection kept, with the reason it was rejected.',
]

/** What is searched, as the FAQ lists it — names of sources, never of customers. */
const SEARCHED = [
  'OpenAlex',
  'arXiv',
  'PubMed',
  'Encyclopedias',
  'The open web',
  'PDFs with OCR',
  'Public-domain books',
  'Video transcripts',
  'Practitioner discussion',
]

/**
 * Subjects for the hero's chips: short enough to sit in a row, and spread across
 * the kinds of thing people actually ask — a craft, a home decision, the body,
 * engineering, history, philosophy. The first is the subject of the log replayed
 * below, so the page's own example is one a reader can try.
 */
const EXAMPLES = [
  'Varroa mite control in beekeeping',
  'Heat pumps in cold climates',
  'Sleep and memory consolidation',
  'Roman concrete durability',
  'CRISPR off-target effects',
  'Thomistic metaphysics',
]

const PRODUCTS = [
  {
    title: 'Answers that cite',
    body: 'Every claim points at a passage you can open, and the passage at the source it came from. Where sources were judged to disagree, the answer says so.',
    art: CitationWireframe,
    href: '#faq',
    link: 'How citations work',
  },
  {
    title: 'A ledger of every source',
    body: 'Kept and dropped alike, with their scores, the rubric version and the stated reason. Read it, sort it, or export it to CSV or RIS.',
    art: LedgerWireframe,
    href: '#record',
    link: 'What gets recorded',
  },
  {
    title: 'A map of what it knows',
    body: 'The key concepts, the sources standing behind each one, and where coverage is short of its target — said in words, not hidden.',
    art: MapWireframe,
    href: '#how',
    link: 'How it is built',
  },
]

const STEPS = [
  {
    icon: Sparkles,
    title: 'You name a subject',
    body: 'One line is a complete request. Peritus picks the depth your plan and balance support.',
  },
  {
    icon: FileSearch,
    title: 'It plans the search',
    body: 'A research brief: five to eight key concepts, and a query set per source type. The concepts are the syllabus everything after is judged against.',
  },
  {
    icon: Layers,
    title: 'Eleven sources are searched at once',
    body: 'Papers, preprints, encyclopedias, PDFs with OCR, books, video transcripts, practitioner discussion. It over-searches on purpose: searching is cheap, downloading is not.',
  },
  {
    icon: ListChecks,
    title: 'Every candidate is screened',
    body: 'Scored for quality and relevance against a versioned rubric. Below the floor, a source is dropped and the reason is recorded. Borderline scores get a second, stronger read.',
  },
  {
    icon: ScrollText,
    title: 'It searches again where it is thin',
    body: 'Coverage is measured per concept. A concept with no accepted source gets its own search, written from the corpus’s own vocabulary — and the search stops with a stated reason, not when it runs out of patience.',
  },
  {
    icon: Network,
    title: 'Then it answers, with citations',
    body: 'Every claim points at a passage you can open. Where sources in the corpus were judged to disagree, the answer says so.',
  },
]

const RECORD_POINTS = [
  {
    icon: FileOutput,
    title: 'Exports you can use',
    body: 'CSV, or RIS for Zotero, Covidence and EndNote.',
  },
  {
    icon: Ruler,
    title: 'A versioned rubric',
    body: 'Each score names the rubric version and the model that judged it.',
  },
  {
    icon: ScanSearch,
    title: 'A second read',
    body: 'Borderline scores are reviewed by a stronger model, and a reversal is recorded.',
  },
  {
    icon: Gauge,
    title: 'Metered spend',
    body: 'Real provider spend per stage, against the build’s hard cap.',
  },
]

const TIERS: { tier: ExpertTier; last: string; lit?: boolean }[] = [
  { tier: 'lite', last: 'The quickest build' },
  { tier: 'standard', last: 'Searches again where coverage is thin', lit: true },
  { tier: 'pro', last: 'The deepest and slowest build' },
]

const container = 'mx-auto w-full max-w-6xl px-4 md:px-8'
const pill =
  'inline-flex h-(--btn-lg) items-center gap-2 rounded-full px-5 text-sm font-medium transition-[background-color,color,border-color,opacity] duration-(--dur-1)'
const pillPrimary = cn(pill, 'bg-accent text-accent-fg hover:opacity-90')
const pillOutline = cn(pill, 'border border-border text-fg-2 hover:bg-raised hover:text-fg')
/** The small mono link at the foot of a card. A row tall, so 44px under a thumb. */
const monoLink =
  'inline-flex h-(--row-h) items-center gap-1.5 rounded-full border border-border px-3.5 font-mono text-label tracking-[0.14em] text-fg-2 uppercase transition-colors duration-(--dur-1) hover:border-fg-4 hover:text-fg'

export default function LandingPage() {
  return (
    <>
      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="relative isolate overflow-hidden border-b border-border-soft">
        <div aria-hidden="true" className="mk-stars absolute inset-0 -z-10" />
        <div aria-hidden="true" className="mk-beam absolute inset-0 -z-10" />

        <div className={cn(container, 'pt-16 pb-10 md:pt-28 md:pb-14')}>
          {/* Two sentences, two blocks: left to wrap as one run the break fell
              after "With", which is the one place it must not. */}
          <h1 className="mk-display text-[clamp(2.75rem,7.2vw,6rem)] text-fg">
            <span className="block max-w-[13ch]">An expert on any subject.</span>{' '}
            <span className="block text-fg-3">With the receipts.</span>
          </h1>
          <p className="mt-6 max-w-[560px] text-base leading-relaxed text-fg-2 md:text-lg md:leading-relaxed">
            Peritus searches real sources, screens every one against a written rubric, and answers
            with citations you can open. It keeps the sources it rejected too, with the reason —
            because the ones it threw away are the evidence that the rest were chosen.
          </p>

          {/* A real form, not a picture of one: it carries the subject into the
              app, by way of sign-in when there is no session. A plain GET, so it
              works before any JavaScript arrives. */}
          <form
            action="/experts/new"
            method="get"
            className="mt-9 flex max-w-[640px] items-center gap-2 rounded-panel border border-border bg-panel/85 p-2 pl-5 transition-colors duration-(--dur-1) focus-within:border-fg-4"
          >
            <label htmlFor="hero-topic" className="sr-only">
              What do you want an expert on?
            </label>
            <input
              id="hero-topic"
              name="topic"
              required
              maxLength={300}
              autoComplete="off"
              placeholder="What do you want an expert on?"
              className="h-12 min-w-0 flex-1 bg-transparent text-base text-fg placeholder:text-fg-3 focus:outline-none"
            />
            <button
              type="submit"
              aria-label="Build this expert"
              className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-accent-fg transition-opacity duration-(--dur-1) hover:opacity-90"
            >
              <ArrowUp className="size-4" />
            </button>
          </form>

          {/* Three on a phone, where each is a 44px row; all six from `sm`. */}
          <ul
            aria-label="Example subjects"
            className="mt-4 flex max-w-[760px] flex-wrap items-center gap-2"
          >
            <li aria-hidden="true" className="mr-1 text-xs text-fg-3">
              Try
            </li>
            {EXAMPLES.map((example, index) => (
              <li key={example} className={cn(index > 2 && 'hidden sm:block')}>
                <Link
                  href={`/experts/new?topic=${encodeURIComponent(example)}`}
                  className="inline-flex h-(--icon-btn-sm) items-center gap-1.5 rounded-full border border-border bg-panel/70 px-3 text-xs text-fg-2 transition-colors duration-(--dur-1) hover:border-fg-4 hover:text-fg"
                >
                  {example}
                  <ArrowUpRight aria-hidden="true" className="size-3 text-fg-3" />
                </Link>
              </li>
            ))}
          </ul>

          <div className="mt-8 flex flex-wrap items-center gap-2">
            <Link href="/signup" className={pillPrimary}>
              {/* Not a second "Sign in": the nav already has one, and two
                  identical calls to action in the first screen said nothing
                  the first did not. */}
              Build your first expert
              <ArrowRight className="size-3.5" />
            </Link>
            <Link href="#how" className={pillOutline}>
              How it works
            </Link>
          </div>

          <ul className="mt-14 grid max-w-4xl gap-x-8 gap-y-4 border-t border-border-soft pt-6 sm:grid-cols-3 md:mt-20">
            {CLAIMS.map((claim) => (
              <li key={claim} className="flex gap-2.5 text-sm leading-relaxed text-fg-2">
                <Plus aria-hidden="true" className="mt-1 size-3.5 shrink-0 text-fg-3" />
                {claim}
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── The product window ───────────────────────────────────────────── */}
      <section className="relative isolate">
        <div aria-hidden="true" className="mk-halo absolute inset-x-0 top-0 -z-10 h-[420px]" />
        <div className={cn(container, 'pt-14 md:pt-20')}>
          <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
            <div>
              <h2 className="mk-display max-w-[18ch] text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
                Watch it decide, one source at a time.
              </h2>
            </div>
            <p className="max-w-[380px] text-sm leading-relaxed text-fg-3">
              This is a recorded log, not an illustration. The drops are in it, each with its reason
              — which is the whole claim.
            </p>
          </div>
          <BuildLogReplay className="mt-8" />
        </div>

        {/* What is searched. Names of sources — never of customers. */}
        <div className={cn(container, 'pt-12 pb-4 md:pt-16')}>
          <p className="text-center text-sm text-fg-3">Where Peritus looks</p>
          <ul className="mt-4 flex flex-wrap items-center justify-center gap-x-7 gap-y-3 text-sm font-medium text-fg-3 md:text-base">
            {SEARCHED.map((name) => (
              <li key={name}>{name}</li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── What you get ─────────────────────────────────────────────────── */}
      <section className={cn(container, 'pt-20 md:pt-28')}>
        <h2 className="mk-display max-w-[20ch] text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
          Three things every expert comes with.
        </h2>
        <ul className="mt-10 grid gap-3 md:grid-cols-3">
          {PRODUCTS.map((product) => (
            <li
              key={product.title}
              className="flex flex-col rounded-panel border border-border-soft bg-panel p-5 transition-colors duration-(--dur-1) hover:border-border md:p-6"
            >
              <h3 className="text-lg font-medium text-fg">{product.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-fg-3">{product.body}</p>
              {/* `mt-auto` on the drawing, not the link: the three bodies are
                  different lengths, and the drawings should share a baseline. */}
              <div className="mt-auto pt-6">
                <product.art />
              </div>
              <Link href={product.href} className={cn(monoLink, 'mt-6 self-start')}>
                {product.link}
                <ArrowUpRight aria-hidden="true" className="size-3" />
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section id="how" className={cn(container, 'scroll-mt-20 pt-20 md:pt-28')}>
        <div className="grid gap-x-16 gap-y-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="lg:sticky lg:top-24 lg:self-start">
            <h2 className="mk-display max-w-[14ch] text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
              What happens when you type a topic
            </h2>
            <p className="mt-4 max-w-[380px] text-sm leading-relaxed text-fg-3">
              Each stage is written to the build log as it happens. You can leave: builds are
              durable, and the log is still there when you come back.
            </p>
          </div>
          <ol className="border-t border-border-soft">
            {STEPS.map((step, index) => (
              <li
                key={step.title}
                className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-x-4 border-b border-border-soft py-6 md:grid-cols-[3.5rem_minmax(0,1fr)]"
              >
                <span className="pt-0.5 font-mono text-xs text-fg-3">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div>
                  <h3 className="flex items-center gap-2.5 text-base font-medium text-fg">
                    <step.icon aria-hidden="true" className="size-4 shrink-0 text-fg-3" />
                    {step.title}
                  </h3>
                  <p className="mt-2 max-w-[560px] text-sm leading-relaxed text-fg-3">
                    {step.body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── What gets recorded ───────────────────────────────────────────── */}
      <section id="record" className={cn(container, 'scroll-mt-20 pt-20 md:pt-28')}>
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
          <div>
            <h2 className="mk-display text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
              What gets recorded
            </h2>
          </div>
          <p className="max-w-[440px] text-sm leading-relaxed text-fg-3">
            Every source lands in a ledger you can read, sort and export — to CSV, or to RIS for
            Zotero, Covidence and EndNote. This is the same table the app shows.
          </p>
        </div>
        <RecordedTable className="mt-8" />
        <p className="mt-4 max-w-[640px] text-xs leading-relaxed text-fg-3">
          A count Peritus does not actually persist is shown as “not recorded”, with the reason —
          never as a zero. A fabricated zero in an evidence record is worse than a visible gap.
        </p>

        <ul className="mt-12 grid gap-x-8 gap-y-8 border-t border-border-soft pt-8 sm:grid-cols-2 lg:grid-cols-4">
          {RECORD_POINTS.map((point) => (
            <li key={point.title}>
              <h3 className="flex items-center gap-2 text-sm font-medium text-fg">
                <point.icon aria-hidden="true" className="size-4 shrink-0 text-fg-3" />
                {point.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-fg-3">{point.body}</p>
            </li>
          ))}
        </ul>
      </section>

      {/* ── Depth ────────────────────────────────────────────────────────────
          Where a product site has prices. Peritus has depths, paid in credits
          that are issued by hand, so that is what the cards say — and every
          button on them goes to sign-up, because there is nothing to buy. */}
      <section id="depth" className={cn(container, 'scroll-mt-20 pt-20 md:pt-28')}>
        <div className="mx-auto max-w-[620px] text-center">
          <h2 className="mk-display text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
            Pick how deep it digs
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-fg-3">
            A depth is paid for in credits and has a hard ceiling on real provider spend. A build
            that crosses its ceiling stops, and the credits are refunded in full.
          </p>
        </div>

        <ul className="mt-10 grid gap-3 md:grid-cols-3">
          {TIERS.map(({ tier, last, lit }) => (
            <li
              key={tier}
              className={cn(
                'flex flex-col rounded-panel border bg-panel p-5 md:p-6',
                lit ? 'mk-lit border-border' : 'border-border-soft'
              )}
            >
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-lg font-medium text-fg">{DEPTH[tier].label}</h3>
                {lit && (
                  <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs font-medium text-accent-fg">
                    Balanced
                  </span>
                )}
              </div>
              <p className="mt-2 min-h-[2.75rem] text-sm leading-relaxed text-fg-3">
                {DEPTH[tier].blurb}
              </p>
              <ul className="mt-5 space-y-3 border-t border-border-soft pt-5 text-sm text-fg-2">
                {[...DEPTH[tier].hint.split(' · '), last].map((line) => (
                  <li key={line} className="flex gap-2.5">
                    <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-fg-3" />
                    <span className="first-letter:uppercase">{line}</span>
                  </li>
                ))}
              </ul>
              <Link
                href="/signup"
                aria-label={`Get started — ${DEPTH[tier].label}`}
                className={cn(lit ? pillPrimary : pillOutline, 'mt-8 justify-center')}
              >
                Get started
              </Link>
            </li>
          ))}
        </ul>
        <p className="mx-auto mt-6 max-w-[620px] text-center text-xs leading-relaxed text-fg-3">
          Not sure? Leave it on Auto, and Peritus picks the deepest depth your plan allows and your
          balance can pay for. There is no checkout: credits are issued by hand while billing is in
          private beta.
        </p>
      </section>

      {/* ── Questions ────────────────────────────────────────────────────── */}
      <section id="faq" className={cn(container, 'scroll-mt-20 pt-20 md:pt-28')}>
        <div className="grid gap-x-16 gap-y-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <div className="flex flex-col">
            <h2 className="mk-display max-w-[14ch] text-[clamp(1.75rem,3.6vw,2.75rem)] text-fg">
              Answered plainly, limits included.
            </h2>
            <div className="mt-8 rounded-card border border-border-soft bg-panel p-5 lg:mt-auto">
              <p className="text-sm font-medium text-fg">Still have a question?</p>
              <p className="mt-1 text-sm leading-relaxed text-fg-3">Email us and ask.</p>
              <a
                href="mailto:hello@peritus.app"
                className={cn(pillPrimary, 'mt-4 h-(--row-h) px-4')}
              >
                hello@peritus.app
              </a>
            </div>
          </div>
          <Faq />
        </div>
      </section>

      {/* ── The close ────────────────────────────────────────────────────── */}
      <section className="relative isolate mt-20 overflow-hidden border-t border-border-soft md:mt-28">
        <div aria-hidden="true" className="mk-stars absolute inset-0 -z-10" />
        <div aria-hidden="true" className="mk-horizon absolute inset-0 -z-10" />
        <div className={cn(container, 'py-24 text-center md:py-36')}>
          <h2 className="mk-display mx-auto max-w-[16ch] text-[clamp(2.25rem,5.4vw,4.25rem)] text-fg">
            Name a subject. Read the receipts.
          </h2>
          <p className="mx-auto mt-5 max-w-[460px] text-sm leading-relaxed text-fg-2 md:text-base md:leading-relaxed">
            No answer without a citation. No citation without a source you can read.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
            <Link href="/signup" className={pillPrimary}>
              Build your first expert
              <ArrowRight className="size-3.5" />
            </Link>
            <Link href="/login" className={pillOutline}>
              Sign in
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
