import type { Metadata } from "next";
import {
  Cinzel,
  JetBrains_Mono,
  Literata,
  UnifrakturMaguntia,
} from "next/font/google";
import { ThemeProvider } from "next-themes";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Three faces, three jobs. The app is a reading surface for a corpus, so the
// type has to read as a book rather than a console — but the technical claims
// (slugs, counts, citation markers) still need the monospace credibility they
// had, so JetBrains Mono stays on exactly that duty and nothing else.

/** Body and reading surfaces. Literata was drawn as an e-reader face — a real
 * book serif, but with a generous x-height and open apertures meant to survive
 * a backlit screen at small sizes. It replaced EB Garamond, whose very small
 * x-height and fine strokes read beautifully at display sizes and tiredly at
 * paragraph sizes, which is most of this app. */
const literata = Literata({
  variable: "--font-literata",
  subsets: ["latin"],
  style: ["normal", "italic"],
  display: "swap",
});

/** Display: titles, running heads, eyebrows. Roman inscriptional capitals in
 * the Trajan lineage — the title-page voice. Caps-only in practice; its
 * lowercase is serviceable but the whole point is the capitals. */
const cinzel = Cinzel({
  variable: "--font-cinzel",
  subsets: ["latin"],
  display: "swap",
});

/** One ornamental glyph: the illuminated initial in the wordmark. Blackletter
 * is close to unreadable at UI sizes, so it is confined to a single letter and
 * never inherited — see components/brand/wordmark.tsx. */
const unifraktur = UnifrakturMaguntia({
  variable: "--font-unifraktur",
  subsets: ["latin"],
  weight: "400",
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
      className={`${literata.variable} ${cinzel.variable} ${unifraktur.variable} ${jetBrainsMono.variable} h-full antialiased`}
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
