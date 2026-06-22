import Link from "next/link";
import { notFound } from "next/navigation";
import { ProductDetail } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import { getScentGradient } from "@/lib/scentColor";
import ProductReviewSection from "@/components/ProductReviewSection";

async function getProductDetail(id: string): Promise<ProductDetail | null> {
  const gatewayUrl = process.env.GATEWAY_URL ?? "http://gateway:4000";

  try {
    const response = await fetch(`${gatewayUrl}/api/products/${id}`, { cache: "no-store" });
    if (!response.ok) return null;
    return response.json();
  } catch {
    return null;
  }
}

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const detail = await getProductDetail(id);

  if (!detail) {
    notFound();
  }

  const { product, reviews } = detail;
  const scentGradient = getScentGradient(product.origin);

  return (
    <main style={{ maxWidth: "880px", margin: "0 auto", padding: "48px 24px" }}>
      <Link
        href="/"
        style={{
          color: "var(--color-text-secondary)",
          fontSize: "13px",
          textDecoration: "none",
          letterSpacing: "0.04em",
        }}
      >
        ← 목록으로
      </Link>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1.1fr 1fr",
          gap: "40px",
          marginTop: "20px",
          alignItems: "start",
        }}
      >
        <div
          style={{
            aspectRatio: "4 / 5",
            background: scentGradient,
            display: "flex",
            alignItems: "flex-end",
            padding: "20px",
          }}
        >
          <span
            style={{
              color: "rgba(255,255,255,0.9)",
              fontSize: "12px",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
            }}
          >
            {product.origin}
          </span>
        </div>

        <header style={{ paddingTop: "8px" }}>
          <h1
            style={{
              fontSize: "26px",
              margin: 0,
              letterSpacing: "0.03em",
              textTransform: "uppercase",
              fontWeight: 700,
            }}
          >
            {product.name}
          </h1>
          <p
            style={{
              color: "var(--color-text-secondary)",
              marginTop: "12px",
              fontSize: "14px",
              lineHeight: 1.6,
            }}
          >
            {product.description}
          </p>
          <p style={{ fontSize: "18px", fontWeight: 700, marginTop: "16px" }}>
            {formatPrice(product.priceWon)}
          </p>
        </header>
      </div>

      <div style={{ marginTop: "40px" }}>
        <ProductReviewSection productId={product.id} initialReviews={reviews ?? []} />
      </div>
    </main>
  );
}
