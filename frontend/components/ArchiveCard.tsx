import Link from "next/link";
import { Review } from "@/lib/types";

type ArchiveReview = Review & { productName?: string };

const BADGE_CLASS: Record<Review["sentimentLabel"], string> = {
  POSITIVE: "ac-badge-positive",
  NEGATIVE: "ac-badge-negative",
  MIXED: "ac-badge-mixed",
};

export default function ArchiveCard({ review }: { review: ArchiveReview }) {
  const isLowConfidence = review.confidenceScore < 0.7;

  const dateLabel = review.createdAt
    ? new Date(review.createdAt).toLocaleDateString("ko-KR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
      })
    : null;

  return (
    <div className="ac-wrap">
      <div className="ac-meta">
        <Link href={`/products/${review.productId}`} className="ac-product">
          {review.productName ?? `#${review.productId}`}
        </Link>
        <span className={BADGE_CLASS[review.sentimentLabel]}>{review.sentimentLabel}</span>
      </div>

      <p className="ac-text">{review.reviewText}</p>

      <div className="ac-footer">
        <span>확신도 {(review.confidenceScore * 100).toFixed(1)}%</span>
        <span>{Number(review.latencyMs).toFixed(0)}ms</span>
        {dateLabel && <span>{dateLabel}</span>}
      </div>

      {isLowConfidence && (
        <p className="ac-low-confidence">
          ⚠ 분석 신뢰도가 낮습니다. 이 모델은 영어 리뷰에 최적화되어 있어요.
        </p>
      )}
    </div>
  );
}
