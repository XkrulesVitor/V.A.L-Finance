import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "ia-trading",
    template: "%s",
  },
  description:
    "Protótipo de IA de trading em cripto: coleta indicadores, roda backtests e mede se decisões guiadas por LLM batem uma estratégia simples.",
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
