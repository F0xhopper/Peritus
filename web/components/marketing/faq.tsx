import { cn } from '@/lib/cn'

/**
 * The FAQ, as native `<details>`.
 *
 * Native because it works before hydration, it is keyboard- and
 * screen-reader-correct for free, and find-in-page opens a closed answer — none
 * of which a hand-rolled accordion gets without work. Styled with the
 * grid-rows collapse, the one layout animation the design permits.
 *
 * The answers are also where the product's limits are stated plainly. Claiming
 * less than a reader might assume is the point: an evidence tool that oversells
 * its screening is worse than one that has none.
 */
const ITEMS: { question: string; answer: React.ReactNode }[] = [
  {
    question: 'What is a tier?',
    answer: (
      <>
        How deep the search goes. A lite build searches and screens fewer sources and answers from
        fewer passages; pro runs more discovery rounds, follows more citations, and puts more
        evidence in front of each answer. Each tier has a credit price and a hard ceiling on real
        provider spend — a build that crosses its ceiling stops, and the credits are refunded in
        full.
      </>
    ),
  },
  {
    question: 'How do citations work?',
    answer: (
      <>
        An answer is composed only from passages that were actually retrieved, and each inline
        <span className="mx-1 font-mono text-xs text-accent">[n]</span> marker points at one of
        them. Opening it shows the passage and the source it came from. If an answer ever cites a
        number that resolves to nothing, it is shown as plain text rather than dressed up as a
        reference.
      </>
    ),
  },
  {
    question: 'Which kinds of source are searched?',
    answer: (
      <>
        Open ones: journals and preprints through OpenAlex, arXiv and PubMed, encyclopedias, web
        pages, PDFs with OCR, books in the public domain, video transcripts, and practitioner
        discussion. You can also add your own — a PDF, a note, or a page behind a login that
        discovery could never reach.
      </>
    ),
  },
  {
    question: 'Does it show where sources disagree?',
    answer: (
      <>
        Where <em>sources in that corpus</em> were judged to disagree, yes — resolved down to the
        passages on each side, with a one-line statement of what is in dispute. Note the wording: a
        corpus is tens of sources, not the literature, and Peritus does not claim to detect
        contradictions in a field.
      </>
    ),
  },
  {
    question: 'Is this systematic review software?',
    answer: (
      <>
        No, and it should not be used as if it were. Screening is a single model pass with a second
        read on borderline cases — there is no dual human review, no conflict resolution, and no
        calibration set, so Peritus reports no sensitivity, recall or precision figures, because any
        number there would be invented. What it produces is the data a review asks you to{' '}
        <em>report</em>: what was searched, what was screened, what was excluded and why.
      </>
    ),
  },
  {
    question: 'What does it not do?',
    answer: (
      <>
        There is no checkout — credits are issued by hand while billing is in private beta. There is
        no account deletion, no persona regeneration without a rebuild, and no email when a build
        finishes; builds are durable, so the log is still there when you come back.
      </>
    ),
  },
]

export function Faq({ className }: { className?: string }) {
  return (
    <div className={cn('divide-y divide-border-soft rounded-card bg-panel', className)}>
      {ITEMS.map((item) => (
        <details key={item.question} className="group px-4">
          <summary className="flex cursor-pointer list-none items-center gap-2 py-3 text-sm font-medium text-fg marker:hidden">
            <span className="min-w-0 flex-1">{item.question}</span>
            <span
              aria-hidden="true"
              className="shrink-0 text-fg-4 transition-transform duration-(--dur-2) ease-(--ease-out) group-open:rotate-45"
            >
              +
            </span>
          </summary>
          <div className="pb-3 text-sm leading-relaxed text-fg-3">{item.answer}</div>
        </details>
      ))}
    </div>
  )
}
