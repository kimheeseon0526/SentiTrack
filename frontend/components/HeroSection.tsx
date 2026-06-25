"use client";

import Link from "next/link";
import { useAuth } from "@/lib/AuthContext";

const STEPS = [
  { label: "향수 선택" },
  { label: "리뷰 작성" },
  { label: "AI 감성 분석" },
  { label: "MY ARCHIVE 기록" },
];

export default function HeroSection() {
  const { user, isLoading } = useAuth();

  function handleScrollToProducts() {
    document.getElementById("products")?.scrollIntoView({ behavior: "smooth" });
  }

  const archiveHref = !isLoading && user ? "/me" : "/login";

  return (
    <section
      style={{
        width: "100%",
        backgroundColor: "#f5f0e8",
        padding: "80px 24px 72px",
      }}
    >
      <div style={{ maxWidth: "720px", margin: "0 auto" }}>
        <p
          style={{
            fontSize: "11px",
            fontWeight: 700,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--color-text-secondary)",
            marginBottom: "20px",
          }}
        >
          AI-POWERED FRAGRANCE REVIEW
        </p>

        <h1
          style={{
            fontSize: "clamp(28px, 5vw, 48px)",
            fontWeight: 700,
            letterSpacing: "-0.01em",
            lineHeight: 1.2,
            margin: "0 0 20px",
            color: "var(--color-text-primary)",
          }}
        >
          당신의 향을 기억합니다
        </h1>

        <p
          style={{
            fontSize: "15px",
            lineHeight: 1.8,
            color: "var(--color-text-secondary)",
            margin: "0 0 48px",
          }}
        >
          향수 리뷰를 남기면 AI가 감성을 분석합니다.
          <br />
          긍정과 아쉬움이 쌓일수록 당신만의 향 취향이 완성됩니다.
        </p>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0",
            flexWrap: "wrap",
            marginBottom: "48px",
            rowGap: "12px",
          }}
        >
          {STEPS.map((step, i) => (
            <div key={step.label} style={{ display: "flex", alignItems: "center" }}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  backgroundColor: "rgba(94, 76, 56, 0.08)",
                  padding: "8px 14px",
                }}
              >
                <span
                  style={{
                    fontSize: "11px",
                    fontWeight: 700,
                    color: "var(--color-text-secondary)",
                    opacity: 0.6,
                    minWidth: "14px",
                  }}
                >
                  {i + 1}
                </span>
                <span
                  style={{
                    fontSize: "12px",
                    fontWeight: 600,
                    letterSpacing: "0.04em",
                    color: "var(--color-text-primary)",
                    whiteSpace: "nowrap",
                  }}
                >
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <span
                  style={{
                    fontSize: "13px",
                    color: "var(--color-text-secondary)",
                    opacity: 0.5,
                    padding: "0 6px",
                  }}
                >
                  →
                </span>
              )}
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap" }}>
          <button
            onClick={handleScrollToProducts}
            style={{
              backgroundColor: "var(--color-accent)",
              color: "#fff",
              border: "none",
              padding: "13px 28px",
              fontSize: "13px",
              fontWeight: 600,
              letterSpacing: "0.06em",
              cursor: "pointer",
            }}
          >
            향수 둘러보기
          </button>

          <Link
            href={archiveHref}
            style={{
              backgroundColor: "transparent",
              color: "var(--color-text-primary)",
              border: "1px solid var(--color-border)",
              padding: "13px 28px",
              fontSize: "13px",
              fontWeight: 600,
              letterSpacing: "0.06em",
              textDecoration: "none",
              display: "inline-block",
            }}
          >
            MY ARCHIVE
          </Link>
        </div>
      </div>
    </section>
  );
}
