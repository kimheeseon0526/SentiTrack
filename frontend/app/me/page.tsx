"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { MyReview } from "@/lib/types";
import { getScentGradient } from "@/lib/scentColor";

interface ScentStat {
  category: string;
  count: number;
}

const SENTIMENT_COLORS: Record<MyReview["sentimentLabel"], { bg: string; border: string; text: string }> = {
  POSITIVE: {
    bg: "var(--color-positive-bg)",
    border: "var(--color-positive-border)",
    text: "var(--color-positive-text)",
  },
  NEGATIVE: {
    bg: "var(--color-negative-bg)",
    border: "var(--color-negative-border)",
    text: "var(--color-negative-text)",
  },
  MIXED: {
    bg: "var(--color-mixed-bg)",
    border: "var(--color-mixed-border)",
    text: "var(--color-mixed-text)",
  },
};

function computeScentStats(reviews: MyReview[], label: "POSITIVE" | "NEGATIVE"): ScentStat[] {
  const filtered = reviews.filter((r) => r.sentimentLabel === label);
  const counts = new Map<string, number>();

  for (const review of filtered) {
    const key = review.scentCategory;
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count);
}

function ScentTagList({ stats }: { stats: ScentStat[] }) {
  if (stats.length === 0) {
    return (
      <p style={{ color: "var(--color-text-secondary)", fontSize: "13px" }}>
        아직 기록이 없어요.
      </p>
    );
  }

  return (
    <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
      {stats.map((scent) => (
        <div
          key={scent.category}
          style={{
            background: getScentGradient(scent.category),
            padding: "10px 16px",
            display: "flex",
            alignItems: "center",
            gap: "8px",
          }}
        >
          <span
            style={{
              color: "rgba(255,255,255,0.95)",
              fontSize: "12px",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontWeight: 700,
            }}
          >
            {scent.category}
          </span>
          <span style={{ color: "rgba(255,255,255,0.8)", fontSize: "11px" }}>
            ×{scent.count}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function MyArchivePage() {
  const router = useRouter();
  const { user, isLoading: isAuthLoading, logout } = useAuth();

  const [reviews, setReviews] = useState<MyReview[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (isAuthLoading) return;

    if (!user) {
      router.push("/login");
      return;
    }

    fetch("/api/me/reviews", {
      headers: { Authorization: `Bearer ${user.token}` },
    })
      .then((res) => res.json())
      .then((data) => setReviews(Array.isArray(data) ? data : []))
      .catch(() => setReviews([]))
      .finally(() => setIsLoading(false));
  }, [user, isAuthLoading, router]);

  if (isAuthLoading || !user) {
    return null;
  }

  const positiveCount = reviews.filter((r) => r.sentimentLabel === "POSITIVE").length;
  const negativeCount = reviews.filter((r) => r.sentimentLabel === "NEGATIVE").length;
  const mixedCount = reviews.filter((r) => r.sentimentLabel === "MIXED").length;
  const favoriteScents = computeScentStats(reviews, "POSITIVE");
  const dislikedScents = computeScentStats(reviews, "NEGATIVE");

  return (
    <main style={{ maxWidth: "880px", margin: "0 auto", padding: "56px 24px" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          marginBottom: "40px",
        }}
      >
        <div>
          <h1
            style={{
              fontSize: "24px",
              margin: 0,
              letterSpacing: "0.06em",
              textTransform: "uppercase",
              fontWeight: 700,
            }}
          >
            My Archive
          </h1>
          <p style={{ color: "var(--color-text-secondary)", marginTop: "8px", fontSize: "14px" }}>
            {user.email}
          </p>
        </div>
        <button
          onClick={() => {
            logout();
            router.push("/");
          }}
          style={{
            background: "none",
            border: "1px solid var(--color-border)",
            padding: "8px 16px",
            fontSize: "12px",
            letterSpacing: "0.04em",
            color: "var(--color-text-secondary)",
          }}
        >
          로그아웃
        </button>
      </header>

      {isLoading && (
        <p style={{ color: "var(--color-text-secondary)", fontSize: "14px" }}>불러오는 중...</p>
      )}

      {!isLoading && reviews.length === 0 && (
        <p style={{ color: "var(--color-text-secondary)", fontSize: "14px" }}>
          아직 작성한 리뷰가 없습니다. 향수를 둘러보고 첫 리뷰를 남겨보세요.
        </p>
      )}

      {!isLoading && reviews.length > 0 && (
        <>
          <section style={{ marginBottom: "40px" }}>
            <div style={{ display: "flex", gap: "12px", marginBottom: "32px", flexWrap: "wrap" }}>
              <div style={statBoxStyle}>
                <span style={statNumberStyle}>{reviews.length}</span>
                <span style={statLabelStyle}>전체 리뷰</span>
              </div>
              <div style={statBoxStyle}>
                <span style={{ ...statNumberStyle, color: "var(--color-positive-text)" }}>
                  {positiveCount}
                </span>
                <span style={statLabelStyle}>긍정 리뷰</span>
              </div>
              <div style={statBoxStyle}>
                <span style={{ ...statNumberStyle, color: "var(--color-negative-text)" }}>
                  {negativeCount}
                </span>
                <span style={statLabelStyle}>아쉬운 리뷰</span>
              </div>
              {mixedCount > 0 && (
                <div style={statBoxStyle}>
                  <span style={{ ...statNumberStyle, color: "var(--color-mixed-text)" }}>
                    {mixedCount}
                  </span>
                  <span style={statLabelStyle}>혼합 리뷰</span>
                </div>
              )}
            </div>

            <div style={{ marginBottom: "28px" }}>
              <h2 style={sectionTitleStyle}>선호하는 향</h2>
              <ScentTagList stats={favoriteScents} />
            </div>

            <div>
              <h2 style={sectionTitleStyle}>싫어하는 향</h2>
              <ScentTagList stats={dislikedScents} />
            </div>
          </section>

          <section>
            <h2 style={{ ...sectionTitleStyle, marginBottom: "16px" }}>내가 쓴 리뷰</h2>

            {reviews.map((review) => (
              <div
                key={review.id}
                style={{
                  backgroundColor: SENTIMENT_COLORS[review.sentimentLabel].bg,
                  borderLeft: `4px solid ${SENTIMENT_COLORS[review.sentimentLabel].border}`,
                  padding: "16px 20px",
                  marginBottom: "10px",
                  boxShadow: "0 1px 3px rgba(58, 46, 38, 0.05)",
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: "12px",
                    color: "var(--color-text-secondary)",
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                  }}
                >
                  {review.productName}
                  <span
                    style={{
                      marginLeft: "8px",
                      opacity: 0.6,
                      fontWeight: 400,
                      textTransform: "none",
                    }}
                  >
                    {review.scentCategory}
                  </span>
                </p>
                <p style={{ margin: "6px 0 0", lineHeight: 1.6 }}>{review.reviewText}</p>
              </div>
            ))}
          </section>
        </>
      )}
    </main>
  );
}

const statBoxStyle: React.CSSProperties = {
  backgroundColor: "var(--color-surface)",
  padding: "16px 24px",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  minWidth: "100px",
  boxShadow: "0 1px 3px rgba(58, 46, 38, 0.06)",
};

const statNumberStyle: React.CSSProperties = {
  fontSize: "24px",
  fontWeight: 700,
};

const statLabelStyle: React.CSSProperties = {
  fontSize: "11px",
  color: "var(--color-text-secondary)",
  marginTop: "4px",
};

const sectionTitleStyle: React.CSSProperties = {
  fontSize: "13px",
  fontWeight: 700,
  color: "var(--color-text-secondary)",
  letterSpacing: "0.05em",
  marginBottom: "12px",
};
