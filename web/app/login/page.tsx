import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GoogleSignIn } from "@/components/auth/google-sign-in";
import { LoginForm } from "@/components/auth/login-form";
import { Logo } from "@/components/brand/wordmark";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  const safeNext = next && next.startsWith("/") ? next : "/experts";

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <Link href="/" aria-label="Peritus — home">
        <Logo />
      </Link>
      <Card className="w-full max-w-sm rounded-lg">
        <CardHeader>
          <CardTitle className="text-base font-medium">Sign in</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error === "google" && (
            <p className="text-sm text-destructive">
              Google sign-in didn&apos;t complete. Try again, or use your email
              below.
            </p>
          )}
          <GoogleSignIn next={safeNext} />
          <div className="rule-ornament text-eyebrow">or</div>
          <LoginForm next={safeNext} />
        </CardContent>
      </Card>
    </div>
  );
}
