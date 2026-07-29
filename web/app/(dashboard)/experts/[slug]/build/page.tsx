import { notFound } from "next/navigation";
import { BuildProgress } from "@/components/experts/build-progress";
import { getExpert } from "@/lib/api/data";

// Reachable at any time, not just while a build is in flight: the event log is
// durable, so this doubles as the build history for a finished or failed
// expert. That is also why it does not redirect a `ready` expert away — the
// page you were sent to after clicking "Start build" should not yank itself
// out from under you the moment the build succeeds.

export default async function ExpertBuildPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const expert = await getExpert(slug);

  if (!expert) {
    notFound();
  }

  return (
    <BuildProgress
      slug={expert.name}
      topic={expert.topic}
      initialStatus={expert.status}
      initialError={expert.error}
    />
  );
}
