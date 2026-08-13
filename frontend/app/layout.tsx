import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Kotodama - AI Game Generator",
  description: "Create unique games with AI-powered multi-agent system",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
