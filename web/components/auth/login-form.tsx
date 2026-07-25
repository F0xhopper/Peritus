"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2Icon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  InputOTP,
  InputOTPGroup,
  InputOTPSlot,
} from "@/components/ui/input-otp";

const emailSchema = z.object({
  email: z.string().trim().email("Enter a valid email address"),
});

const otpSchema = z.object({
  code: z.string().length(6, "Enter the 6-digit code"),
});

async function postJson(url: string, body: unknown) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.error ?? "Something went wrong.");
  }
  return res;
}

export function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [step, setStep] = React.useState<"email" | "otp">("email");
  const [email, setEmail] = React.useState("");
  const [serverError, setServerError] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState(false);

  const emailForm = useForm<z.infer<typeof emailSchema>>({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: "" },
  });

  const otpForm = useForm<z.infer<typeof otpSchema>>({
    resolver: zodResolver(otpSchema),
    defaultValues: { code: "" },
  });

  async function onSubmitEmail(values: z.infer<typeof emailSchema>) {
    setServerError(null);
    setPending(true);
    try {
      await postJson("/api/auth/otp", { email: values.email });
      setEmail(values.email);
      setStep("otp");
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not send code.");
    } finally {
      setPending(false);
    }
  }

  async function onSubmitOtp(values: z.infer<typeof otpSchema>) {
    setServerError(null);
    setPending(true);
    try {
      await postJson("/api/auth/verify", { email, token: values.code });
      router.push(next);
      router.refresh();
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Invalid code.");
    } finally {
      setPending(false);
    }
  }

  async function resendCode() {
    setServerError(null);
    setPending(true);
    try {
      await postJson("/api/auth/otp", { email });
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not resend code.");
    } finally {
      setPending(false);
    }
  }

  if (step === "email") {
    return (
      <Form {...emailForm}>
        <form
          onSubmit={emailForm.handleSubmit(onSubmitEmail)}
          className="flex flex-col gap-4"
        >
          <span className="text-eyebrow text-muted-foreground">Step one of two</span>
          <FormField
            control={emailForm.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email</FormLabel>
                <FormControl>
                  <Input
                    type="email"
                    placeholder="you@example.com"
                    autoComplete="email"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          {serverError && (
            <p className="text-sm text-destructive">{serverError}</p>
          )}
          <Button type="submit" disabled={pending}>
            {pending && <Loader2Icon className="animate-spin" />}
            Send code
          </Button>
        </form>
      </Form>
    );
  }

  return (
    <Form {...otpForm}>
      <form
        onSubmit={otpForm.handleSubmit(onSubmitOtp)}
        className="flex flex-col gap-4"
      >
        <span className="text-eyebrow text-muted-foreground">Step two of two</span>
        <p className="text-sm text-muted-foreground">
          We sent a 6-digit code to <span className="text-foreground">{email}</span>.
        </p>
        <FormField
          control={otpForm.control}
          name="code"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Code</FormLabel>
              <FormControl>
                <InputOTP maxLength={6} autoFocus {...field}>
                  <InputOTPGroup>
                    {Array.from({ length: 6 }).map((_, i) => (
                      <InputOTPSlot key={i} index={i} />
                    ))}
                  </InputOTPGroup>
                </InputOTP>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        {serverError && (
          <p className="text-sm text-destructive">{serverError}</p>
        )}
        <Button type="submit" disabled={pending}>
          {pending && <Loader2Icon className="animate-spin" />}
          Verify
        </Button>
        <div className="flex items-center justify-between text-sm">
          <button
            type="button"
            onClick={() => setStep("email")}
            className="text-muted-foreground hover:text-foreground"
          >
            Use a different email
          </button>
          <button
            type="button"
            onClick={resendCode}
            disabled={pending}
            className="text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            Resend code
          </button>
        </div>
      </form>
    </Form>
  );
}
