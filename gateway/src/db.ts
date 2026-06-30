import mysql from "mysql2/promise";
import { requireEnv } from "./env.js";

const pool = mysql.createPool({
  host: process.env.DB_HOST ?? "shared-db",
  port: Number(process.env.DB_PORT ?? 3306),
  user: requireEnv("DB_USER"),
  password: requireEnv("DB_PASSWORD"),
  database: process.env.DB_NAME ?? "sentitrack",
  waitForConnections: true,
  connectionLimit: 10,
});

export default pool;
