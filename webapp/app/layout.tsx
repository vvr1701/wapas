import type { Metadata } from "next";
import { Inter } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import { Nav } from "@/components/nav";

// Blade's own faces: Inter for text, TASA Orbiter (shipped in razorpay/blade)
// for headings. Code face is Blade's Menlo stack, set in globals.css.
const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const tasa = localFont({
  src: "./tasa-orbiter.woff2",
  variable: "--font-tasa",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Wapas — Revenue Recovery",
  description: "Revenue that slipped away, brought wapas.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${tasa.variable}`}>
      <body className="min-h-screen">
        <div className="flex min-h-screen">
          <Nav />
          <main className="min-w-0 flex-1 px-8 py-7">{children}</main>
        </div>
      </body>
    </html>
  );
}
