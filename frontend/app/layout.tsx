import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

/*
 * Geist Sans + Geist Mono, carregados por `next/font` (self-hosted, sem
 * requisição a terceiros e sem salto de layout).
 *
 * A escolha não é neutra: Geist Mono foi desenhado para interface densa e
 * numeral tabular, que é exatamente o que esta página é. Todo número
 * comparável do site sai nele; a prosa sai no Sans.
 */

export const metadata: Metadata = {
  title: {
    default: "V.A.L Finance",
    template: "%s · V.A.L Finance",
  },
  description:
    "Sistema de decisão para cripto: cérebro de linguagem sob autoridade de um motor de risco, medido contra o mercado em tempo real.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="pt-BR"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      style={
        {
          "--fonte-sans": GeistSans.style.fontFamily,
          "--fonte-mono": GeistMono.style.fontFamily,
        } as React.CSSProperties
      }
    >
      <body>{children}</body>
    </html>
  );
}
