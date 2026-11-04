/* ============================================================
   PropStein — Preview Environment Basic Auth Guard
   Fail-closed auth verification for preview environments.
   ============================================================ */

export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

export interface AuthResult {
  authorized: boolean;
  status?: number;
  reason?: string;
  headers?: Record<string, string>;
}

export function checkPreviewAuth(
  authorizationHeader: string | null | undefined,
  env: {
    PREVIEW_AUTH_PASSWORD?: string;
    PREVIEW_AUTH_USER?: string;
    NODE_ENV?: string;
  }
): AuthResult {
  const pw = env.PREVIEW_AUTH_PASSWORD;
  if (!pw) {
    if (env.NODE_ENV === "development") return { authorized: true };
    return { authorized: false, status: 503, reason: "Preview not configured" };
  }

  const [scheme, token] = (authorizationHeader ?? "").split(" ");
  if (scheme === "Basic" && token) {
    try {
      const decoded = atob(token);
      const i = decoded.indexOf(":");
      if (i > -1) {
        const user = decoded.slice(0, i);
        const pass = decoded.slice(i + 1);
        const expected = env.PREVIEW_AUTH_USER ?? "propstein";
        if (user === expected && safeEqual(pass, pw)) {
          return { authorized: true };
        }
      }
    } catch {}
  }

  return { authorized: false, status: 401, reason: "Unauthorized" };
}

export function handlePreviewMiddleware(
  req: { headers: { get: (name: string) => string | null } },
  env: Record<string, string | undefined> = process.env
): AuthResult {
  const result = checkPreviewAuth(req.headers.get("authorization"), env);
  if (result.authorized) {
    return { authorized: true };
  }
  if (result.status === 503) {
    return { authorized: false, status: 503, reason: "Preview not configured" };
  }
  return {
    authorized: false,
    status: 401,
    reason: "Unauthorized",
    headers: {
      "WWW-Authenticate": 'Basic realm="PropStein Terminal Preview"',
    },
  };
}

