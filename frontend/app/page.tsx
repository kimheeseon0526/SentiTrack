import ProductCard from "@/components/ProductCard";
import { Product } from "@/lib/types";

async function getProducts(): Promise<Product[]> {
  const gatewayUrl = process.env.GATEWAY_URL ?? "http://gateway:4000";

  try {
    const response = await fetch(`${gatewayUrl}/api/products`, { cache: "no-store" });
    if (!response.ok) return [];
    return response.json();
  } catch {
    return [];
  }
}

export default async function Home() {
  const products = await getProducts();

  return (
    <main style={{ maxWidth: "1040px", margin: "0 auto", padding: "56px 24px" }}>
      <header style={{ marginBottom: "40px" }}>
        <h1
          style={{
            fontSize: "26px",
            margin: 0,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            fontWeight: 700,
          }}
        >
          SentiTrack
        </h1>
        <p style={{ color: "var(--color-text-secondary)", marginTop: "8px", fontSize: "14px" }}>
          향수 — AI가 분석하는 실시간 리뷰 감성
        </p>
      </header>

      {products.length === 0 ? (
        <p style={{ color: "var(--color-text-secondary)", fontSize: "14px" }}>
          상품을 불러올 수 없습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: "28px",
          }}
        >
          {products.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      )}
    </main>
  );
}
