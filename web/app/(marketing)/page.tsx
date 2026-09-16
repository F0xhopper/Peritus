import {
  ArrowRight,
  FileSearch,
  Layers,
  ListChecks,
  Network,
  ScrollText,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'

import { BuildLogReplay } from '@/components/marketing/build-log-replay'
import { Faq } from '@/components/marketing/faq'
import { RecordedTable } from '@/components/marketing/recorded-table'

export const metadata = {
  // `absolute`: the root template would otherwise append " · Peritus" to a
  // title that already starts with the name.
  title: { absolute: 'Peritus — experts built from the evidence, with the receipts' },
}

/**
 * The landing page.
 *
 * The hero is a real recorded build log rather than an illustration, because
 * the product's claim is about the record it keeps and an illustration cannot
 * make that claim. No gradients, no glow, no stock imagery — the same near-black
 * canvas the app uses, with more air.
 */
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

export default function LandingPage() {
  return (
    <>
      <section className="mx-auto w-full max-w-5xl px-4 pt-12 pb-10 md:px-6 md:pt-16">
        <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="max-w-[640px]">
            <h1 className="text-hero font-medium tracking-tight text-fg">
              An expert on any subject — and the receipts for every source behind it.
            </h1>
            <p className="mt-4 text-base leading-relaxed text-fg-2">
              Peritus searches real sources, screens every one of them against a written rubric, and
              answers with citations you can open. It keeps the sources it rejected too, with the
              reason — because the ones it threw away are the evidence that the rest were chosen.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-2">
              <Link
                href="/login"
                className="inline-flex h-(--btn-lg) items-center gap-1.5 rounded-row bg-accent px-4 text-sm font-medium text-accent-fg transition-[filter] duration-(--dur-1) hover:brightness-110"
              >
                {/* Not a second "Sign in": the nav already has one, and two
                    identical calls to action in the first screen said nothing
                    the first did not. */}
                Build your first expert
                <ArrowRight className="size-3.5" />
              </Link>
              <Link
                href="#how"
                className="inline-flex h-(--btn-lg) items-center rounded-row border border-border px-4 text-sm text-fg-2 transition-colors duration-(--dur-1) hover:bg-raised hover:text-fg"
              >
                How it works
              </Link>
            </div>
            <p className="mt-3 text-xs text-fg-3">
              No answer without a citation. No citation without a source you can read.
            </p>
          </div>

          {/* Beside the headline from `lg`; under it, shorter, below that. */}
          <BuildLogReplay />
        </div>
      </section>

      <section id="how" className="mx-auto w-full max-w-5xl scroll-mt-20 px-4 py-10 md:px-6">
        <h2 className="text-lg font-medium text-fg">What happens when you type a topic</h2>
        <ol className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((step, index) => (
            <li key={step.title} className="rounded-card bg-panel p-4">
              <div className="flex items-center gap-2">
                <span className="grid size-6 place-items-center rounded-chip bg-accent/12 font-mono text-xs text-accent">
                  {index + 1}
                </span>
                <step.icon className="size-4 text-fg-4" aria-hidden="true" />
              </div>
              <h3 className="mt-2.5 text-sm font-medium text-fg">{step.title}</h3>
              <p className="mt-1 text-sm leading-relaxed text-fg-3">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mx-auto w-full max-w-5xl px-4 py-10 md:px-6">
        <h2 className="text-lg font-medium text-fg">What gets recorded</h2>
        <p className="mt-1 max-w-[640px] text-sm leading-relaxed text-fg-3">
          Every source lands in a ledger you can read, sort and export — to CSV, or to RIS for
          Zotero, Covidence and EndNote. This is the same table the app shows.
        </p>
        <RecordedTable className="mt-4" />
        <p className="mt-3 max-w-[640px] text-xs leading-relaxed text-fg-3">
          A count Peritus does not actually persist is shown as “not recorded”, with the reason —
          never as a zero. A fabricated zero in an evidence record is worse than a visible gap.
        </p>
      </section>

      <section className="mx-auto w-full max-w-[680px] px-4 py-10 md:px-6">
        <h2 className="text-lg font-medium text-fg">Questions</h2>
        <Faq className="mt-4" />
      </section>
    </>
  )
}
