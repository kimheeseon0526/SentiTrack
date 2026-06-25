import ProductCard from "@/components/ProductCard";
import HeroSection from "@/components/HeroSection";
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
    <>
      <HeroSection />

      <main style={{ maxWidth: "1040px", margin: "0 auto", padding: "56px 24px" }}>
        <div id="products">
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
        </div>
      </main>
    </>
  );
}
