import type { Metadata } from "next";
import { Figtree } from "next/font/google";
import "./globals.css";

const font = Figtree({ subsets: ["latin"], weight: ["400", "500", "600", "800"] });

export const metadata: Metadata = {
  title: "Shortlist: find companies hiring for your skills",
  description: "Paste your resume and see open roles ranked by how well your skills fit.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={font.className}>{children}</body>
    </html>
  );
}