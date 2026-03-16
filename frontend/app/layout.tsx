import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Peritus – Domain Expert Learning System",
  description:
    "Build a graph-grounded AI expert for any topic. Learn through structured courses and open-ended conversation.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div className="page-wrapper">
          <nav>
            <a href="/" className="brand">PERITUS</a>
            <a href="/">Home</a>
            <a href="/experts">My Experts</a>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
