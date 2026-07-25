import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { AppBreadcrumbs } from "@/components/breadcrumbs/app-breadcrumbs";
import { Separator } from "@/components/ui/separator";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { getExperts, getRecentConversations, safely } from "@/lib/api/data";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Sidebar chrome degrades to empty rather than erroring the whole shell when
  // the API is unreachable — the page content reports the real problem.
  const [experts, conversations] = await Promise.all([
    safely(() => getExperts(), []),
    safely(() => getRecentConversations(8), []),
  ]);

  return (
    // The shell is exactly one viewport tall and scrolling happens inside the
    // inset, so a chat can pin its composer to the bottom and scroll only its
    // transcript.
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar experts={experts} conversations={conversations} />
      <SidebarInset className="min-h-0">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border/60 px-4">
          <SidebarTrigger className="-ml-1" />
          <Separator
            orientation="vertical"
            className="data-vertical:h-4 data-vertical:self-auto"
          />
          {/* The trail resolves slugs and chat ids to readable names using the
              lists already fetched above, so it costs no extra request. */}
          <AppBreadcrumbs experts={experts} conversations={conversations} />
        </header>
        <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto p-4 md:p-6">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
