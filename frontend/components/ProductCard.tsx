"use client";

import { useState } from "react";
import Link from "next/link";
import { Product } from "@/lib/types";
import { formatPrice } from "@/lib/format";
import { getScentGradient } from "@/lib/scentColor";

export default function ProductCard({ product }: { product: Product }) {
  const [isHovered, setIsHovered] = useState(false);
  const scentGradient = getScentGradient(product.origin);

  return (
    <Link
      href={`/products/${product.id}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        display: "block",
        textDecoration: "none",
        color: "inherit",
        backgroundColor: "var(--color-surface)",
        padding: "20px",
        boxShadow: isHovered
          ? "0 6px 16px rgba(58, 46, 38, 0.1)"
          : "0 1px 3px rgba(58, 46, 38, 0.06)",
        transition: "box-shadow 0.25s ease, transform 0.25s ease",
        transform: isHovered ? "translateY(-2px)" : "translateY(0)",
      }}
    >
      <div
        style={{
          aspectRatio: "1 / 1",
          background: scentGradient,
          marginBottom: "16px",
          display: "flex",
          alignItems: "flex-end",
          padding: "12px",
        }}
      >
        <span
          style={{
            color: "rgba(255,255,255,0.9)",
            fontSize: "11px",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
          }}
        >
          {product.origin}
        </span>
      </div>

      <h3
        style={{
          margin: 0,
          fontSize: "16px",
          fontWeight: 700,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
        }}
      >
        {product.name}
      </h3>

      <p
        style={{
          margin: "8px 0 0",
          fontSize: "13px",
          color: "var(--color-text-secondary)",
          lineHeight: 1.5,
        }}
      >
        {product.description}
      </p>

      <p style={{ margin: "14px 0 0", fontSize: "15px", fontWeight: 700 }}>
        {formatPrice(product.priceWon)}
      </p>
    </Link>
  );
}
