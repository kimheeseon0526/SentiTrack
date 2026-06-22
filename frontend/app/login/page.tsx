"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleLogin() {
    if (!email || !password) {
      setErrorMessage("이메일과 비밀번호를 입력해주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        setErrorMessage(data.error ?? "로그인에 실패했습니다.");
        return;
      }

      login({ token: data.token, email: data.email });
      router.push("/");
    } catch {
      setErrorMessage("서버에 연결할 수 없습니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main style={{ maxWidth: "420px", margin: "0 auto", padding: "80px 24px" }}>
      <h1
        style={{
          fontSize: "22px",
          margin: "0 0 32px",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontWeight: 700,
        }}
      >
        Login
      </h1>

      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        <input
          type="email"
          placeholder="이메일"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          disabled={isSubmitting}
          style={inputStyle}
        />
        <input
          type="password"
          placeholder="비밀번호"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={isSubmitting}
          style={inputStyle}
        />
        <button onClick={handleLogin} disabled={isSubmitting} style={buttonStyle}>
          {isSubmitting ? "로그인 중..." : "로그인"}
        </button>
      </div>

      {errorMessage && (
        <p style={{ color: "var(--color-negative-text)", fontSize: "13px", marginTop: "12px" }}>
          {errorMessage}
        </p>
      )}

      <p style={{ fontSize: "13px", marginTop: "24px", color: "var(--color-text-secondary)" }}>
        계정이 없으신가요?{" "}
        <Link href="/signup" style={{ color: "var(--color-accent)" }}>
          회원가입
        </Link>
      </p>
    </main>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  backgroundColor: "var(--color-surface-raised)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border)",
  padding: "12px",
  fontSize: "14px",
  outline: "none",
};

const buttonStyle: React.CSSProperties = {
  backgroundColor: "var(--color-accent)",
  color: "#fff",
  border: "none",
  padding: "12px",
  fontSize: "14px",
  fontWeight: 600,
  letterSpacing: "0.04em",
};
