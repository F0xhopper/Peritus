import { notFound } from "next/navigation";
import Link from "next/link";
import { MessageSquareIcon } from "lucide-react";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/experts/status-badge";
import { ConversationList } from "@/components/chat/conversation-list";
import { NewChatComposer } from "@/components/chat/new-chat-composer";
import { PersonaAvatar } from "@/components/experts/persona-avatar";
import { getExpert, getExpertConversations, safely } from "@/lib/api/data";
import { personaLabel } from "@/lib/persona";

export default async function ExpertChatPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const expert = await getExpert(slug);

  if (!expert) {
    notFound();
  }

  const conversations = await safely(() => getExpertConversations(slug), []);
  const ready = expert.status === "ready";
  const expertLabel = personaLabel(expert.persona_name) ?? expert.topic;

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        icon={MessageSquareIcon}
        title={`Chat with ${expertLabel}`}
        action={<StatusBadge status={expert.status} />}
      />

      <div className="flex flex-1 flex-col justify-end gap-6">
        <div className="mx-auto flex w-full max-w-3xl flex-col items-center text-center">
          {/* Whoever you are about to talk to, above the box you talk into —
              the header names the page, this names the person. */}
          <PersonaAvatar label={expertLabel} size="lg" className="mb-3" />
          <h2 className="text-base font-medium">{expertLabel}</h2>
          {expert.persona_name ? (
            <p className="text-eyebrow mt-1 text-muted-foreground">
              {expert.topic}
            </p>
          ) : null}
          <p className="mt-1 text-sm text-muted-foreground">
            {ready ? (
              <>
                Answers are grounded in this expert&apos;s{" "}
                <Link
                  href={`/experts/${expert.name}`}
                  className="underline underline-offset-2 hover:text-foreground"
                >
                  {expert.source_count.toLocaleString()} sources
                </Link>{" "}
                and cited passage by passage.
              </>
            ) : (
              <>
                This expert is {expert.status}. Chat opens once the build
                finishes.
              </>
            )}
          </p>
        </div>

        <NewChatComposer slug={expert.name} ready={ready} />

        <ConversationList conversations={conversations} />
      </div>
    </div>
  );
}
