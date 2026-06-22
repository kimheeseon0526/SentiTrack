"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";

type Step = "request" | "verify";

export default function SignupPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [step, setStep] = useState<Step>("request");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleRequestCode() {
    if (!email || !password) {
      setErrorMessage("이메일과 비밀번호를 입력해주세요.");
      return;
    }

    if (password.length < 8) {
      setErrorMessage("비밀번호는 8자 이상이어야 합니다.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/auth/signup/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        setErrorMessage(data.error ?? "회원가입 요청에 실패했습니다.");
        return;
      }

      setStep("verify");
    } catch {
      setErrorMessage("서버에 연결할 수 없습니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleVerifyCode() {
    if (!code) {
      setErrorMessage("인증 코드를 입력해주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch("/api/auth/signup/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code }),
      });

      const data = await response.json();

      if (!response.ok) {
        setErrorMessage(data.error ?? "인증에 실패했습니다.");
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
        Sign Up
      </h1>

      {step === "request" && (
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
            placeholder="비밀번호 (8자 이상)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={isSubmitting}
            style={inputStyle}
          />
          <button onClick={handleRequestCode} disabled={isSubmitting} style={buttonStyle}>
            {isSubmitting ? "전송 중..." : "인증 코드 받기"}
          </button>
        </div>
      )}

      {step === "verify" && (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <p style={{ fontSize: "13px", color: "var(--color-text-secondary)" }}>
            {email}로 인증 코드를 보냈습니다. (스팸함도 확인해주세요)
          </p>
          <input
            type="text"
            placeholder="6자리 인증 코드"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={isSubmitting}
            maxLength={6}
            style={inputStyle}
          />
          <button onClick={handleVerifyCode} disabled={isSubmitting} style={buttonStyle}>
            {isSubmitting ? "확인 중..." : "인증 완료"}
          </button>
        </div>
      )}

      {errorMessage && (
        <p style={{ color: "var(--color-negative-text)", fontSize: "13px", marginTop: "12px" }}>
          {errorMessage}
        </p>
      )}

      <p style={{ fontSize: "13px", marginTop: "24px", color: "var(--color-text-secondary)" }}>
        이미 계정이 있으신가요?{" "}
        <Link href="/login" style={{ color: "var(--color-accent)" }}>
          로그인
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
