import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Christianity AI Assistant",
  description: "Phase 1 skeleton",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
