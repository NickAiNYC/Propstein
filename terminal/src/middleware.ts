import { NextRequest, NextResponse } from "next/server";

export function middleware(req: NextRequest) {
  const previewPassword = process.env.PREVIEW_AUTH_PASSWORD;
  if (!previewPassword) {
    return NextResponse.next();
  }

  const authHeader = req.headers.get("authorization");
  if (!authHeader) {
    return new NextResponse("Authentication required for preview environment", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="PropStein Terminal Preview"',
      },
    });
  }

  const authValue = authHeader.split(" ")[1];
  if (!authValue) {
    return new NextResponse("Invalid authorization", { status: 401 });
  }

  try {
    const decoded = atob(authValue);
    const [user, pwd] = decoded.split(":");
    const expectedUser = process.env.PREVIEW_AUTH_USER || "propstein";

    if (user === expectedUser && pwd === previewPassword) {
      return NextResponse.next();
    }
  } catch {
    // Malformed base64
  }

  return new NextResponse("Unauthorized", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="PropStein Terminal Preview"',
    },
  });
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
