"use client";

import { useState } from "react";
import ReviewForm from "@/components/ReviewForm";
import ReviewCard from "@/components/ReviewCard";
import { Review } from "@/lib/types";

type Filter = "ALL" | "POSITIVE" | "NEGATIVE";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "ALL", label: "전체보기" },
  { key: "POSITIVE", label: "긍정적 향기" },
  { key: "NEGATIVE", label: "아쉬운 향기" },
];

export default function ProductReviewSection({
  productId,
  initialReviews,
}: {
  productId: number;
  initialReviews: Review[];
}) {
  const [reviews, setReviews] = useState<Review[]>(initialReviews ?? []);
  const [filter, setFilter] = useState<Filter>("ALL");

  function handleReviewAdded(review: Review) {
    setReviews((prev) => [review, ...prev]);
  }

  const filtered =
    filter === "ALL" ? reviews : reviews.filter((r) => r.sentimentLabel === filter);

  const emptyMessage =
    reviews.length === 0
      ? "아직 등록된 리뷰가 없습니다. 첫 리뷰를 남겨보세요."
      : "해당 감성의 리뷰가 없습니다.";

  return (
    <section>
      <ReviewForm productId={productId} onReviewAdded={handleReviewAdded} />

      <div style={{ marginTop: "32px" }}>
        <div className="review-tabs">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setFilter(key)}
              className={`review-tab${filter === key ? " review-tab-active" : ""}`}
            >
              {label}
            </button>
          ))}
        </div>

        <h2 className="reviews-count">
          {filter === "ALL" ? `리뷰 ${reviews.length}개` : `${filtered.length}개`}
        </h2>

        {filtered.length === 0 && (
          <p style={{ color: "var(--color-text-secondary)", fontSize: "14px" }}>
            {emptyMessage}
          </p>
        )}

        {filtered.map((review) => (
          <ReviewCard key={review.id} review={review} />
        ))}
      </div>
    </section>
  );
}
