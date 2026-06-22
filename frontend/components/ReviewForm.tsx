"use client";

import { useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";
import { Review } from "@/lib/types";

export default function ReviewForm({
  productId,
  onReviewAdded,
}: {
  productId: number;
  onReviewAdded: (review: Review) => void;
}) {
  const { user } = useAuth();
  const [text, setText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isButtonHovered, setIsButtonHovered] = useState(false);

  async function handleSubmit() {
    if (!user) {
      setErrorMessage("로그인이 필요합니다.");
      return;
    }

    const trimmed = text.trim();

    if (trimmed.length === 0) {
      setErrorMessage("리뷰 내용을 입력해주세요.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const response = await fetch(`/api/products/${productId}/reviews`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${user.token}`,
        },
        body: JSON.stringify({ text: trimmed }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        setErrorMessage(data?.error ?? "분석 중 오류가 발생했습니다.");
        return;
      }

      const review: Review = await response.json();
      onReviewAdded(review);
      setText("");
    } catch {
      setErrorMessage("서버에 연결할 수 없습니다.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!user) {
    return (
      <div
        style={{
          backgroundColor: "var(--color-surface)",
          padding: "24px",
          textAlign: "center",
          boxShadow: "0 1px 3px rgba(58, 46, 38, 0.06)",
        }}
      >
        <p style={{ fontSize: "14px", color: "var(--color-text-secondary)", margin: 0 }}>
          리뷰를 작성하려면 로그인이 필요합니다.
        </p>
        <Link
          href="/login"
          style={{
            display: "inline-block",
            marginTop: "14px",
            color: "#fff",
            backgroundColor: "var(--color-accent)",
            padding: "10px 24px",
            fontSize: "14px",
            fontWeight: 600,
            letterSpacing: "0.04em",
            textDecoration: "none",
          }}
        >
          로그인하기
        </Link>
      </div>
    );
  }

  const buttonBackground = isSubmitting
    ? "var(--color-border)"
    : isButtonHovered
      ? "var(--color-text-primary)"
      : "var(--color-accent)";

  return (
    <div
      style={{
        backgroundColor: "var(--color-surface)",
        padding: "24px",
        boxShadow: "0 1px 3px rgba(58, 46, 38, 0.06)",
      }}
    >
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="이 향수에 대한 리뷰를 영어로 입력하세요 (예: Smooth and well balanced, would buy again.)"
        rows={4}
        maxLength={2000}
        disabled={isSubmitting}
        style={{
          width: "100%",
          backgroundColor: "var(--color-surface-raised)",
          color: "var(--color-text-primary)",
          border: "1px solid var(--color-border)",
          padding: "12px",
          fontSize: "14px",
          resize: "vertical",
          outline: "none",
        }}
      />

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: "12px",
        }}
      >
        <span style={{ fontSize: "12px", color: "var(--color-text-secondary)" }}>
          {text.length} / 2000
        </span>

        <button
          onClick={handleSubmit}
          disabled={isSubmitting}
          onMouseEnter={() => setIsButtonHovered(true)}
          onMouseLeave={() => setIsButtonHovered(false)}
          style={{
            backgroundColor: buttonBackground,
            color: "#fff",
            border: "none",
            padding: "10px 24px",
            fontSize: "14px",
            fontWeight: 600,
            letterSpacing: "0.04em",
            transition: "background-color 0.25s ease",
          }}
        >
          {isSubmitting ? "분석 중..." : "리뷰 등록"}
        </button>
      </div>

      {errorMessage && (
        <p style={{ color: "var(--color-negative-text)", fontSize: "13px", marginTop: "8px" }}>
          {errorMessage}
        </p>
      )}
    </div>
  );
}
