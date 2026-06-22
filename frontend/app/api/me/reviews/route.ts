const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://gateway:4000";

export async function GET(request: Request) {
  const authHeader = request.headers.get("authorization");

  try {
    const response = await fetch(`${GATEWAY_URL}/api/me/reviews`, {
      headers: authHeader ? { authorization: authHeader } : {},
      cache: "no-store",
    });

    const data = await response.json();
    return Response.json(data, { status: response.status });
  } catch {
    return Response.json({ error: "gateway unreachable" }, { status: 502 });
  }
}
