export interface Product {
  id: number;
  name: string;
  origin: string;
  description: string;
  priceWon: number;
  imageUrl: string | null;
  createdAt?: string;
}

export interface Review {
  id: number;
  productId: number;
  userId: number;
  reviewText: string;
  sentimentLabel: "POSITIVE" | "NEGATIVE" | "MIXED";
  confidenceScore: number;
  modelVersion: string;
  latencyMs: number;
  createdAt?: string;
}

export interface MyReview extends Review {
  productName: string;
  productOrigin: string;
  scentCategory: string;
}

export interface ProductDetail {
  product: Product;
  reviews: Review[];
}

export interface AuthUser {
  token: string;
  email: string;
}
