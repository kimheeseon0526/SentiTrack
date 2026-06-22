const GATEWAY_URL = process.env.GATEWAY_URL ?? "http://gateway:4000";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();
  const authorization = request.headers.get("authorization");

  try {
    const response = await fetch(`${GATEWAY_URL}/api/products/${id}/reviews`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(authorization ? { Authorization: authorization } : {}),
      },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    return Response.json(data, { status: response.status });
  } catch {
    return Response.json({ error: "gateway unreachable" }, { status: 502 });
  }
}
