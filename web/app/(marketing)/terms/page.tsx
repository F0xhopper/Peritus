import { LegalPage } from '@/components/marketing/legal-page'

export const metadata = {
  title: 'Terms',
  description: 'The terms of using Peritus, including what it does not claim to be.',
}

export default function TermsPage() {
  return (
    <LegalPage title="Terms" updated="12 September 2026">
      <h2>The service</h2>
      <p>
        Peritus searches public sources on a subject you name, screens what it finds, and answers
        questions from the material it kept. It is in private beta. Features may change, and
        availability is not guaranteed.
      </p>

      <h2>What Peritus is not</h2>
      <p>
        These limits are part of the terms because acting as though they did not apply is the main
        way this tool could do harm.
      </p>
      <ul>
        <li>
          <strong>It is not systematic review software.</strong> Screening is a single model pass,
          with a second read on borderline cases. There is no dual human review and no conflict
          resolution. It produces data a review asks you to report; compliance is a property of
          your review, not of a tool.
        </li>
        <li>
          <strong>It does not substitute for professional advice.</strong> Nothing it says is
          medical, legal, financial or safety advice, however well cited.
        </li>
        <li>
          <strong>Its personas are not people.</strong> An expert’s name, bio and voice are
          generated. They are a way of speaking about a corpus, not a claim that a qualified
          individual reviewed anything.
        </li>
        <li>
          <strong>Language models get things wrong.</strong> Answers are grounded in retrieved
          passages and cite them, which makes a mistake checkable — not impossible. Open the
          citations for anything that matters.
        </li>
      </ul>

      <h2>Your account</h2>
      <p>
        Keep access to your email secure; it is how you sign in. You are responsible for what is
        built and asked under your account.
      </p>

      <h2>Credits</h2>
      <p>
        Builds consume credits. Credits are held when a build is enqueued and refunded in full if
        it fails, is cancelled, or stops at its spend ceiling. Chat does not consume credits.
        There is no checkout: credits are issued by hand during the beta and have no cash value.
      </p>

      <h2>Acceptable use</h2>
      <p>
        Do not use Peritus to build a corpus whose purpose is to harass or defame someone, to
        evade the access controls or terms of the sources it searches, or to launder invented
        claims through a citation format. Do not upload material you have no right to use.
      </p>

      <h2>Content and rights</h2>
      <p>
        Sources keep their own copyright; Peritus stores passages of them in order to retrieve and
        cite them, and points at the original. Your topics, uploads and conversations remain
        yours. Publishing an expert grants readers the right to read its corpus record and its
        evidence trail.
      </p>

      <h2>No warranty, and limits</h2>
      <p>
        The service is provided as is, without warranty of any kind. To the extent the law allows,
        liability for any loss arising from using it is limited to the credits you paid for the
        build in question.
      </p>

      <h2>Changes</h2>
      <p>
        These terms may change; the date at the top says when they last did. Continuing to use the
        service after a change means accepting it.
      </p>

      <h2>Getting in touch</h2>
      <p>
        <a href="mailto:hello@peritus.app">hello@peritus.app</a>.
      </p>
    </LegalPage>
  )
}
