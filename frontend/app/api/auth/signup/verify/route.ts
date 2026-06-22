const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://gateway:4000";

export async function POST(request: Request) {
  const body = await request.json();

  try {
    const response = await fetch(`${GATEWAY_URL}/api/auth/signup/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await response.json();
    return Response.json(data, { status: response.status });
  } catch {
    return Response.json({ error: "gateway unreachable" }, { status: 502 });
  }
}
