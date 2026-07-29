import type { Metadata } from "next";
import { JetBrains_Mono, Literata } from "next/font/google";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Two faces, two jobs. The app is a reading surface for a corpus, so the type
// has to read as reference material — a book, an encyclopedia entry — rather
// than a console. The technical claims (slugs, counts, citation markers)
// still need the monospace credibility they had, so JetBrains Mono stays on
// exactly that duty and nothing else.

/** Everything read as language: body copy, headings, labels, titles. Literata
 * was drawn as an e-reader face — a real book serif, but with a generous
 * x-height and open apertures meant to survive a backlit screen at small
 * sizes. It replaced EB Garamond, whose very small x-height and fine strokes
 * read beautifully at display sizes and tiredly at paragraph sizes, which is
 * most of this app. */
const literata = Literata({
  variable: "--font-literata",
  subsets: ["latin"],
  style: ["normal", "italic"],
  display: "swap",
});

/** Data only: slugs, counts, code, citation markers, keyboard hints. */
const jetBrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Peritus",
  description:
    "Search the literature a database export misses — and keep a record you can defend.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${literata.variable} ${jetBrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <ThemeProvider attribute="class" defaultTheme="dark" forcedTheme="dark">
          <TooltipProvider>
            {children}
            <Toaster />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
