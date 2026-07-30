import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { AppBreadcrumbs } from "@/components/breadcrumbs/app-breadcrumbs";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import {
  getCurrentUser,
  getExperts,
  getRecentConversations,
  safely,
} from "@/lib/api/data";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Sidebar chrome degrades to empty rather than erroring the whole shell when
  // the API is unreachable — the page content reports the real problem. A
  // dead session still redirects to /login: fetchOrLogin's NotAuthenticatedError
  // throws Next's redirect control-flow error, which `safely` re-throws rather
  // than swallowing (see lib/api/data.ts).
  const [experts, conversations, user] = await Promise.all([
    safely(() => getExperts(), []),
    safely(() => getRecentConversations(8), []),
    safely(() => getCurrentUser(), null),
  ]);

  return (
    // The shell is exactly one viewport tall and scrolling happens inside the
    // inset, so a chat can pin its composer to the bottom and scroll only its
    // transcript.
    <SidebarProvider className="h-svh overflow-hidden">
      <AppSidebar experts={experts} conversations={conversations} user={user} />
      <SidebarInset className="min-h-0 min-w-0">
        {/* No rule under this strip: the sidebar toggle and breadcrumb sit in
            their own row of whitespace, set off from the content below by the
            gap the content wrapper already opens rather than a drawn line. */}
        <header className="flex h-12 shrink-0 items-center gap-3 px-4">
          <SidebarTrigger className="-ml-1" />
          {/* The trail resolves slugs and chat ids to readable names using the
              lists already fetched above, so it costs no extra request. */}
          <AppBreadcrumbs experts={experts} conversations={conversations} />
        </header>
        {/* [&>*]:shrink-0 matters once a page's content (e.g. the merged
            expert Overview) exceeds viewport height: without it, flexbox
            shrinks direct children to fit rather than letting this box
            scroll, because Card's overflow-hidden strips their automatic
            minimum size and leaves nothing to stop the shrink. */}
        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-6 overflow-y-auto p-4 [&>*]:shrink-0 md:p-6">
          {children}
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
