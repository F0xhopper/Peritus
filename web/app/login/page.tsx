import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoginForm } from "@/components/auth/login-form";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <Link href="/" className="flex items-center gap-1 font-medium">
        <span className="text-primary" aria-hidden>
          {">"}
        </span>
        <span className="tracking-tight">peritus</span>
      </Link>
      <Card className="w-full max-w-sm rounded-lg">
        <CardHeader>
          <CardTitle className="text-base font-medium">Sign in</CardTitle>
        </CardHeader>
        <CardContent>
          <LoginForm next={next && next.startsWith("/") ? next : "/dashboard"} />
        </CardContent>
      </Card>
    </div>
  );
}
