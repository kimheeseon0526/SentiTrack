import Fastify from "fastify";
import cors from "@fastify/cors";
import mysql from "mysql2/promise";
import pool from "./db.js";
import { verifyToken } from "./jwt.js";
import { registerAuthRoutes } from "./authRoutes.js";

const INFERENCE_URL = process.env.INFERENCE_URL ?? "http://inference:8000/predict";
const PORT = Number(process.env.PORT ?? 4000);

const app = Fastify({ logger: true });

await app.register(cors, {
  origin: process.env.ALLOWED_ORIGIN ?? "http://frontend:3000",
});

await registerAuthRoutes(app);

interface PredictResult {
  label: string;
  score: number;
  model_version: string;
  latency_ms: number;
}

interface ProductRow extends mysql.RowDataPacket {
  id: number;
  name: string;
  origin: string;
  description: string;
  price_won: number;
  image_url: string | null;
  created_at: string;
}

interface ReviewRow extends mysql.RowDataPacket {
  id: number;
  product_id: number;
  user_id: number;
  review_text: string;
  sentiment_label: string;
  confidence_score: number;
  model_version: string;
  latency_ms: number;
  created_at: string;
}

function toProductDto(row: ProductRow) {
  return {
    id: row.id,
    name: row.name,
    origin: row.origin,
    description: row.description,
    priceWon: row.price_won,
    imageUrl: row.image_url,
    createdAt: row.created_at,
  };
}

function toReviewDto(row: ReviewRow) {
  return {
    id: row.id,
    productId: row.product_id,
    userId: row.user_id,
    reviewText: row.review_text,
    sentimentLabel: row.sentiment_label,
    confidenceScore: Number(row.confidence_score),
    modelVersion: row.model_version,
    latencyMs: Number(row.latency_ms),
    createdAt: row.created_at,
  };
}

function getAuthenticatedUserId(authHeader: string | undefined): number | null {
  if (!authHeader || !authHeader.startsWith("Bearer ")) {
    return null;
  }

  const token = authHeader.slice("Bearer ".length);
  const payload = verifyToken(token);

  return payload?.userId ?? null;
}

app.get("/health", async () => {
  return { status: "ok" };
});

app.get("/api/products", async (request, reply) => {
  try {
    const [rows] = await pool.query<ProductRow[]>(
      `SELECT id, name, origin, description, price_won, image_url, created_at
       FROM sentitrack_products
       ORDER BY id ASC`
    );

    return reply.send(rows.map(toProductDto));
  } catch (error) {
    app.log.error(error, "failed to fetch products");
    return reply.status(500).send({ error: "failed to fetch products" });
  }
});

app.get<{ Params: { id: string } }>("/api/products/:id", async (request, reply) => {
  const productId = Number(request.params.id);

  if (!Number.isInteger(productId)) {
    return reply.status(400).send({ error: "invalid product id" });
  }

  try {
    const [productRows] = await pool.query<ProductRow[]>(
      `SELECT id, name, origin, description, price_won, image_url, created_at
       FROM sentitrack_products
       WHERE id = ?`,
      [productId]
    );

    if (productRows.length === 0) {
      return reply.status(404).send({ error: "product not found" });
    }

    const [reviewRows] = await pool.query<ReviewRow[]>(
      `SELECT id, product_id, user_id, review_text, sentiment_label, confidence_score, model_version, latency_ms, created_at
       FROM sentitrack_reviews
       WHERE product_id = ?
       ORDER BY created_at DESC`,
      [productId]
    );

    return reply.send({
      product: toProductDto(productRows[0]),
      reviews: reviewRows.map(toReviewDto),
    });
  } catch (error) {
    app.log.error(error, "failed to fetch product detail");
    return reply.status(500).send({ error: "failed to fetch product detail" });
  }
});

app.post<{ Params: { id: string }; Body: { text: string } }>(
  "/api/products/:id/reviews",
  async (request, reply) => {
    const userId = getAuthenticatedUserId(request.headers.authorization);

    if (!userId) {
      return reply.status(401).send({ error: "login is required to write a review" });
    }

    const productId = Number(request.params.id);
    const { text } = request.body;

    if (!Number.isInteger(productId)) {
      return reply.status(400).send({ error: "invalid product id" });
    }

    if (!text || text.trim().length === 0) {
      return reply.status(400).send({ error: "text is required" });
    }

    if (text.length > 2000) {
      return reply.status(400).send({ error: "text must be 2000 characters or fewer" });
    }

    const [productRows] = await pool.query<ProductRow[]>(
      `SELECT id FROM sentitrack_products WHERE id = ?`,
      [productId]
    );

    if (productRows.length === 0) {
      return reply.status(404).send({ error: "product not found" });
    }

    let prediction: PredictResult;

    try {
      const inferenceResponse = await fetch(INFERENCE_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (!inferenceResponse.ok) {
        app.log.error({ status: inferenceResponse.status }, "inference server returned an error");
        return reply.status(502).send({ error: "inference service unavailable" });
      }

      prediction = (await inferenceResponse.json()) as PredictResult;
    } catch (error) {
      app.log.error(error, "failed to reach inference server");
      return reply.status(502).send({ error: "inference service unreachable" });
    }

    try {
      const [result] = await pool.query(
        `INSERT INTO sentitrack_reviews
          (product_id, user_id, review_text, sentiment_label, confidence_score, model_version, latency_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?)`,
        [
          productId,
          userId,
          text,
          prediction.label,
          prediction.score,
          prediction.model_version,
          prediction.latency_ms,
        ]
      );

      const insertId = (result as mysql.ResultSetHeader).insertId;

      return reply.status(201).send({
        id: insertId,
        productId,
        userId,
        reviewText: text,
        sentimentLabel: prediction.label,
        confidenceScore: prediction.score,
        modelVersion: prediction.model_version,
        latencyMs: prediction.latency_ms,
      });
    } catch (error) {
      app.log.error(error, "failed to save review to database");
      return reply.status(500).send({ error: "failed to save review" });
    }
  }
);

app.get("/api/me/reviews", async (request, reply) => {
  const userId = getAuthenticatedUserId(request.headers.authorization);

  if (!userId) {
    return reply.status(401).send({ error: "login is required" });
  }

  try {
    const [rows] = await pool.query<(ReviewRow & { product_name: string; product_origin: string; scent_category: string })[]>(
      `SELECT r.id, r.product_id, r.user_id, r.review_text, r.sentiment_label, r.confidence_score,
              r.model_version, r.latency_ms, r.created_at,
              p.name AS product_name, p.origin AS product_origin, p.scent_category
       FROM sentitrack_reviews r
       JOIN sentitrack_products p ON r.product_id = p.id
       WHERE r.user_id = ?
       ORDER BY r.created_at DESC`,
      [userId]
    );

    return reply.send(
      rows.map((row) => ({
        ...toReviewDto(row),
        productName: row.product_name,
        productOrigin: row.product_origin,
        scentCategory: row.scent_category,
      }))
    );
  } catch (error) {
    app.log.error(error, "failed to fetch my reviews");
    return reply.status(500).send({ error: "failed to fetch my reviews" });
  }
});

app.listen({ port: PORT, host: "0.0.0.0" }).catch((error) => {
  app.log.error(error);
  process.exit(1);
});
