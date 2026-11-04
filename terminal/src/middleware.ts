import { NextRequest, NextResponse } from "next/server";
import { checkPreviewAuth } from "@/lib/propstein/auth";

export function middleware(req: NextRequest) {
  const result = checkPreviewAuth(req.headers.get("authorization"), process.env);
  if (result.authorized) {
    return NextResponse.next();
  }

  if (result.status === 503) {
    return new NextResponse("Preview not configured", { status: 503 });
  }

  return new NextResponse("Unauthorized", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="PropStein Terminal Preview"',
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
