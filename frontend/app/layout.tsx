import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "V.A.L Finance",
    template: "%s",
  },
  description:
    "V.A.L Finance — protótipo que coleta indicadores de cripto, roda backtests e mede se decisões guiadas por LLM batem uma estratégia simples.",
  robots: { index: false, follow: false },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body className="antialiased">{children}</body>
    </html>
  );
}
