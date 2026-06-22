const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://gateway:4000";

export async function GET() {
  try {
    const response = await fetch(`${GATEWAY_URL}/api/products`, {
      cache: "no-store",
    });

    if (!response.ok) {
      return Response.json({ error: "failed to fetch products" }, { status: response.status });
    }

    const data = await response.json();
    return Response.json(data);
  } catch {
    return Response.json({ error: "gateway unreachable" }, { status: 502 });
  }
}
