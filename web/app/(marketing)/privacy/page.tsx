import { LegalPage } from '@/components/marketing/legal-page'

export const metadata = {
  title: 'Privacy',
  description: 'What Peritus stores, why, and who can see it.',
}

/**
 * Required for Google OAuth and for production. Written to be read, and to be
 * accurate about the specific things this system actually does — a generic
 * privacy page would be both useless and, in places, wrong.
 */
export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy" updated="12 September 2026">
      <h2>What this covers</h2>
      <p>
        Peritus builds subject experts from public sources and answers questions from them. This
        page describes what the service stores while doing that, why each piece exists, and who can
        see it.
      </p>

      <h2>Signing in</h2>
      <p>
        Authentication is handled by Supabase Auth. Signing in with an email code stores your email
        address and an account identifier; signing in with Google stores the same two things, taken
        from the Google profile you consent to share. No password is ever stored, because Peritus
        does not use one.
      </p>
      <p>
        Your session lives in two cookies set by this site, marked
        <code>HttpOnly</code> so no JavaScript on the page can read them, and
        <code>Secure</code> in production. They are the session and nothing else: no analytics, no
        advertising, and no third-party cookies are set anywhere on this site.
      </p>

      <h2>What is stored when you build an expert</h2>
      <ul>
        <li>
          <strong>The topic you typed</strong>, the tier, and the expert’s generated name, bio and
          voice.
        </li>
        <li>
          <strong>Every source the search considered</strong> — its title, address, author where
          known, its quality and relevance scores, the rubric version that judged it, the search
          path that found it, and, for a rejected source, the reason. This is the product, not a
          by-product: the record is the thing you are being given.
        </li>
        <li>
          <strong>The text of accepted sources</strong>, split into passages and stored with vector
          embeddings so they can be retrieved. Only material the source itself published.
        </li>
        <li>
          <strong>A durable event log for each build</strong>, so a build survives a closed laptop
          and can be replayed from where you left it.
        </li>
        <li>
          <strong>Metered provider spend per stage</strong>, so a build’s cost is checkable against
          what it was quoted.
        </li>
      </ul>

      <h2>What is stored when you chat</h2>
      <p>
        Conversations are persisted: your questions, the answers, and the citations each answer
        used. That is what makes a chat resumable and what makes an answer accountable after the
        fact — an answer nobody can re-examine is not an answer with receipts.
      </p>
      <p>
        Each answer also stores a retrieval trail: which passages were retrieved, which reached the
        model, and which the answer cited. It records dispositions and counts, never a confidence or
        a grounding score, because there is no calibration behind such a number.
      </p>

      <h2>Sources you upload</h2>
      <p>
        A PDF, a note or a URL you add is stored, extracted and indexed the same way a discovered
        source is, and is visible only to you unless you publish the expert. A rebuild deletes
        discovered sources and keeps yours.
      </p>

      <h2>Who can see your data</h2>
      <p>
        An expert is private by default: only your account can read it, and only your account can
        ever modify it. Publishing an expert makes its card, its corpus and its evidence trail
        readable by anyone with the link — deliberately, because a public expert whose evidence
        trail was private would be a claim without a receipt. It never makes the expert writable by
        anyone else, and it never exposes your email, your credit balance or your spend.
      </p>

      <h2>Processors</h2>
      <p>
        Peritus sends text to language-model and embedding providers in order to plan a search,
        screen a source, index a passage and compose an answer. It sends search queries to the
        source APIs it searches, and it fetches the public pages and files those return. The
        database and authentication run on Supabase. Nothing is sold, and nothing is shared for
        advertising.
      </p>

      <h2>Retention and deletion</h2>
      <p>
        Deleting an expert deletes its corpus, its passages, its graph and its chats. Account
        deletion is not offered through the interface yet — ask and it will be done by hand. Server
        logs record request identifiers, timings and errors; they never record message or answer
        content.
      </p>

      <h2>Getting in touch</h2>
      <p>
        For access, correction, export or deletion, email{' '}
        <a href="mailto:privacy@peritus.app">privacy@peritus.app</a>.
      </p>
    </LegalPage>
  )
}
