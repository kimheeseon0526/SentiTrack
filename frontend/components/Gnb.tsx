"use client";

import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";

export default function Gnb() {
  const { user, isLoading, logout } = useAuth();

  return (
    <nav
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "20px 24px",
        backgroundColor: "var(--color-surface)",
        borderBottom: "1px solid var(--color-border)",
      }}
    >
      <Link
        href="/"
        style={{
          fontSize: "16px",
          fontWeight: 700,
          color: "var(--color-text-primary)",
          textDecoration: "none",
        }}
      >
        SentiTrack
      </Link>

      <div style={{ display: "flex", gap: "24px", alignItems: "center" }}>
        {!isLoading && !user && (
          <>
            <Link href="/login" style={navLinkStyle}>
              로그인
            </Link>
            <Link href="/signup" style={navLinkStyle}>
              회원가입
            </Link>
          </>
        )}

        {!isLoading && user && (
          <>
            <Link href="/me" style={navLinkStyle}>
              MY ARCHIVE
            </Link>
            <button onClick={logout} style={logoutButtonStyle}>
              로그아웃
            </button>
          </>
        )}
      </div>
    </nav>
  );
}

const navLinkStyle: React.CSSProperties = {
  fontSize: "12px",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-secondary)",
  textDecoration: "none",
};

const logoutButtonStyle: React.CSSProperties = {
  fontSize: "12px",
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--color-text-secondary)",
  background: "none",
  border: "none",
  cursor: "pointer",
  padding: 0,
};
