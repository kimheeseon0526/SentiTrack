import { randomInt } from "node:crypto";
import { FastifyInstance, FastifyReply } from "fastify";
import bcrypt from "bcryptjs";
import mysql from "mysql2/promise";
import pool from "./db.js";
import { signToken } from "./jwt.js";
import { sendVerificationEmail } from "./email.js";

const VERIFICATION_CODE_TTL_MINUTES = 10;
const BCRYPT_SALT_ROUNDS = 10;
const RATE_LIMIT_WINDOW_MS = 15 * 60 * 1000;
const SIGNUP_REQUEST_RATE_LIMIT = { max: 5, windowMs: RATE_LIMIT_WINDOW_MS };
const SIGNUP_VERIFY_RATE_LIMIT = { max: 10, windowMs: RATE_LIMIT_WINDOW_MS };
const LOGIN_RATE_LIMIT = { max: 10, windowMs: RATE_LIMIT_WINDOW_MS };

interface RateLimitPolicy {
  max: number;
  windowMs: number;
}

interface RateLimitEntry {
  count: number;
  resetAt: number;
}

const signupRequestRateLimit = new Map<string, RateLimitEntry>();
const signupVerifyRateLimit = new Map<string, RateLimitEntry>();
const loginRateLimit = new Map<string, RateLimitEntry>();

interface UserRow extends mysql.RowDataPacket {
  id: number;
  email: string;
  password_hash: string;
  is_verified: boolean;
}

interface VerificationRow extends mysql.RowDataPacket {
  id: number;
  email: string;
  code: string;
  expires_at: string;
}

function generateVerificationCode(): string {
  return randomInt(100000, 1000000).toString();
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}

function getRateLimitKey(ip: string, email: string | undefined): string {
  return `${ip}:${email?.trim().toLowerCase() || "unknown"}`;
}

function checkRateLimit(
  store: Map<string, RateLimitEntry>,
  key: string,
  policy: RateLimitPolicy
): { allowed: true } | { allowed: false; retryAfterSeconds: number } {
  const now = Date.now();
  const entry = store.get(key);

  if (!entry || entry.resetAt <= now) {
    store.set(key, { count: 1, resetAt: now + policy.windowMs });
    return { allowed: true };
  }

  if (entry.count >= policy.max) {
    return {
      allowed: false,
      retryAfterSeconds: Math.ceil((entry.resetAt - now) / 1000),
    };
  }

  entry.count += 1;
  return { allowed: true };
}

function sendRateLimitExceeded(reply: FastifyReply, retryAfterSeconds: number) {
  return reply
    .header("Retry-After", retryAfterSeconds.toString())
    .status(429)
    .send({ error: "too many requests, please try again later" });
}

export async function registerAuthRoutes(app: FastifyInstance) {
  app.post<{ Body: { email: string; password: string } }>(
    "/api/auth/signup/request",
    async (request, reply) => {
      const { email, password } = request.body;
      const rateLimit = checkRateLimit(
        signupRequestRateLimit,
        getRateLimitKey(request.ip, email),
        SIGNUP_REQUEST_RATE_LIMIT
      );

      if (!rateLimit.allowed) {
        return sendRateLimitExceeded(reply, rateLimit.retryAfterSeconds);
      }

      if (!email || !isValidEmail(email)) {
        return reply.status(400).send({ error: "valid email is required" });
      }

      if (!password || password.length < 8) {
        return reply.status(400).send({ error: "password must be at least 8 characters" });
      }

      const [existingUsers] = await pool.query<UserRow[]>(
        `SELECT id FROM sentitrack_users WHERE email = ? AND is_verified = TRUE`,
        [email]
      );

      if (existingUsers.length > 0) {
        return reply.status(409).send({ error: "email already registered" });
      }

      const passwordHash = await bcrypt.hash(password, BCRYPT_SALT_ROUNDS);
      const code = generateVerificationCode();
      const expiresAt = new Date(Date.now() + VERIFICATION_CODE_TTL_MINUTES * 60 * 1000);

      try {
        await pool.query(
          `INSERT INTO sentitrack_users (email, password_hash, is_verified)
           VALUES (?, ?, FALSE)
           ON DUPLICATE KEY UPDATE password_hash = VALUES(password_hash)`,
          [email, passwordHash]
        );

        await pool.query(
          `INSERT INTO sentitrack_email_verifications (email, code, expires_at) VALUES (?, ?, ?)`,
          [email, code, expiresAt]
        );

        await sendVerificationEmail(email, code);

        return reply.status(200).send({ message: "verification code sent" });
      } catch (error) {
        app.log.error(error, "failed to start signup");
        return reply.status(500).send({ error: "failed to send verification email" });
      }
    }
  );

  app.post<{ Body: { email: string; code: string } }>(
    "/api/auth/signup/verify",
    async (request, reply) => {
      const { email, code } = request.body;
      const rateLimit = checkRateLimit(
        signupVerifyRateLimit,
        getRateLimitKey(request.ip, email),
        SIGNUP_VERIFY_RATE_LIMIT
      );

      if (!rateLimit.allowed) {
        return sendRateLimitExceeded(reply, rateLimit.retryAfterSeconds);
      }

      if (!email || !code) {
        return reply.status(400).send({ error: "email and code are required" });
      }

      try {
        const [verificationRows] = await pool.query<VerificationRow[]>(
          `SELECT id, email, code, expires_at
           FROM sentitrack_email_verifications
           WHERE email = ? AND code = ?
           ORDER BY created_at DESC
           LIMIT 1`,
          [email, code]
        );

        if (verificationRows.length === 0) {
          return reply.status(400).send({ error: "invalid verification code" });
        }

        const verification = verificationRows[0];

        if (new Date(verification.expires_at).getTime() < Date.now()) {
          return reply.status(400).send({ error: "verification code expired" });
        }

        await pool.query(`UPDATE sentitrack_users SET is_verified = TRUE WHERE email = ?`, [
          email,
        ]);

        await pool.query(`DELETE FROM sentitrack_email_verifications WHERE email = ?`, [email]);

        const [userRows] = await pool.query<UserRow[]>(
          `SELECT id, email FROM sentitrack_users WHERE email = ?`,
          [email]
        );

        const user = userRows[0];
        const token = signToken({ userId: user.id, email: user.email });

        return reply.status(200).send({ token, email: user.email });
      } catch (error) {
        app.log.error(error, "failed to verify signup");
        return reply.status(500).send({ error: "failed to verify code" });
      }
    }
  );

  app.post<{ Body: { email: string; password: string } }>(
    "/api/auth/login",
    async (request, reply) => {
      const { email, password } = request.body;
      const rateLimit = checkRateLimit(
        loginRateLimit,
        getRateLimitKey(request.ip, email),
        LOGIN_RATE_LIMIT
      );

      if (!rateLimit.allowed) {
        return sendRateLimitExceeded(reply, rateLimit.retryAfterSeconds);
      }

      if (!email || !password) {
        return reply.status(400).send({ error: "email and password are required" });
      }

      try {
        const [userRows] = await pool.query<UserRow[]>(
          `SELECT id, email, password_hash, is_verified FROM sentitrack_users WHERE email = ?`,
          [email]
        );

        if (userRows.length === 0) {
          return reply.status(401).send({ error: "invalid email or password" });
        }

        const user = userRows[0];

        if (!user.is_verified) {
          return reply.status(403).send({ error: "email not verified" });
        }

        const passwordMatches = await bcrypt.compare(password, user.password_hash);

        if (!passwordMatches) {
          return reply.status(401).send({ error: "invalid email or password" });
        }

        const token = signToken({ userId: user.id, email: user.email });

        return reply.status(200).send({ token, email: user.email });
      } catch (error) {
        app.log.error(error, "failed to log in");
        return reply.status(500).send({ error: "failed to log in" });
      }
    }
  );
}
