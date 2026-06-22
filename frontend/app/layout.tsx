import type { Metadata } from "next";
import "./globals.css";
import Gnb from "@/components/Gnb";
import { AuthProvider } from "@/lib/AuthContext";

export const metadata: Metadata = {
  title: "SentiTrack",
  description: "실시간 리뷰 감성 분석 모니터",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>
        <AuthProvider>
          <Gnb />
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
