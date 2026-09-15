/**
 * The shell for the privacy and terms pages.
 *
 * A 680px measure and document typography — the same reading surface the
 * Overview page uses, because these are documents and should read like the rest
 * of the product rather than like a pasted-in legal appendix.
 */
export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string
  updated: string
  children: React.ReactNode
}) {
  return (
    <article className="mx-auto w-full max-w-[680px] px-4 pt-10 pb-16 md:px-6">
      <h1 className="text-title font-medium text-fg">{title}</h1>
      <p className="mt-1 text-sm text-fg-3">Last updated {updated}.</p>
      <div
        className={[
          'mt-8 space-y-4 text-base leading-relaxed text-fg-2',
          // Typography for the prose inside, scoped here so each page stays
          // plain markup.
          '[&_h2]:mt-8 [&_h2]:text-lg [&_h2]:font-medium [&_h2]:text-fg',
          '[&_ul]:space-y-2 [&_ul]:pl-5 [&_ul]:list-disc',
          '[&_li]:leading-relaxed',
          '[&_strong]:font-medium [&_strong]:text-fg',
          '[&_a]:text-fg [&_a]:underline [&_a]:underline-offset-2',
          '[&_code]:mx-0.5 [&_code]:rounded-[4px] [&_code]:bg-raised [&_code]:px-1 [&_code]:font-mono [&_code]:text-[0.85em]',
          '[&_em]:italic',
        ].join(' ')}
      >
        {children}
      </div>
    </article>
  )
}
