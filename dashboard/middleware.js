export const config = {
  matcher: "/((?!_next/static|favicon|api/health).*)",
};

export default function middleware(request) {
  const auth = request.headers.get("authorization");
  const expected =
    "Basic " + btoa(`${process.env.DASH_USER || "yibo"}:${process.env.DASH_PASS || ""}`);
  if (!process.env.DASH_PASS) {
    return new Response("Server misconfigured: DASH_PASS env not set", { status: 500 });
  }
  if (auth !== expected) {
    return new Response("Authentication required.", {
      status: 401,
      headers: { "WWW-Authenticate": 'Basic realm="trending-radar"' },
    });
  }
  return undefined;
}
