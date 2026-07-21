import { Review } from "@/lib/types";

const LOW_CONFIDENCE_THRESHOLD = 0.7;

const SENTIMENT_STYLES: Record<Review["sentimentLabel"], { bg: string; border: string; text: string }> = {
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

export default function ReviewCard({ review }: { review: Review }) {
  const sentimentStyle = SENTIMENT_STYLES[review.sentimentLabel];
  const isLowConfidence = Number(review.confidenceScore) < LOW_CONFIDENCE_THRESHOLD;

  return (
    <div
      style={{
        backgroundColor: sentimentStyle.bg,
        borderLeft: `4px solid ${sentimentStyle.border}`,
        padding: "16px 20px",
        marginBottom: "10px",
        boxShadow: "0 1px 3px rgba(58, 46, 38, 0.05)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "16px",
        }}
      >
        <p style={{ margin: 0, flex: 1, fontSize: "14px", lineHeight: 1.6, wordBreak: "break-word" }}>
          {review.reviewText}
        </p>
        <span
          style={{
            color: sentimentStyle.text,
            fontWeight: 700,
            fontSize: "13px",
            letterSpacing: "0.05em",
            whiteSpace: "nowrap",
            paddingTop: "2px",
          }}
        >
          {review.sentimentLabel}
        </span>
      </div>

      <div
        style={{
          display: "flex",
          gap: "16px",
          marginTop: "10px",
          fontSize: "11px",
          fontFamily: "var(--font-mono)",
          color: "var(--color-text-secondary)",
        }}
      >
        <span>확신도 {(Number(review.confidenceScore) * 100).toFixed(1)}%</span>
        <span>{Number(review.latencyMs).toFixed(0)}ms</span>
      </div>

      {isLowConfidence && (
        <p
          style={{
            margin: "10px 0 0",
            fontSize: "12px",
            color: "var(--color-text-secondary)",
            fontStyle: "italic",
          }}
        >
          ⚠ 분석 신뢰도가 낮습니다. 이 모델은 영어 리뷰에 최적화되어 있습니다.
        </p>
      )}
    </div>
  );
}
