// A mirror of `_slugify` in api/src/peritus/api/routes/experts.py:
//
//     re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:80]
//
// Needed because `POST /experts/build` answers with an SSE stream rather than
// the created expert, so the client has no other way to learn which URL the
// build landed on.
//
// Deliberately NOT load-bearing: the route handler confirms the slug against
// the backend and falls back to a lookup if it misses (see
// app/api/experts/build/route.ts). If this and the Python ever drift, the
// build flow degrades to one extra request rather than to a 404.
//
// Order matters — Python strips the hyphens *before* truncating, so a topic
// whose 80th character is a separator keeps a trailing hyphen. Reversing these
// two steps produces a different slug for those inputs.

export function slugifyTopic(topic: string): string {
  return topic
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}
