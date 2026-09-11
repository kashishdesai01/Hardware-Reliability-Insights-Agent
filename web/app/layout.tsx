import type { Metadata } from "next";
import Link from "next/link";
import "./styles.css";

export const metadata: Metadata = {
  title: "HRIA · Reliability evidence",
  description: "Evidence-first hardware reliability analysis",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <Link className="brand" href="/">
            <span className="brandMark">H</span>
            <span>Hardware Reliability</span>
          </Link>
          <nav>
            <Link href="/">Ask</Link>
            <Link href="/explorer">Explorer</Link>
            <Link href="/evals">Evals</Link>
          </nav>
          <div className="status"><i /> Synthetic dataset</div>
        </header>
        {children}
      </body>
    </html>
  );
}
