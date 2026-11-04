import { NextRequest, NextResponse } from "next/server";
import { handlePreviewMiddleware } from "@/lib/propstein/auth";

export function middleware(req: NextRequest) {
  const result = handlePreviewMiddleware(req, process.env);
  if (result.authorized) {
    return NextResponse.next();
  }

  return new NextResponse(result.reason, {
    status: result.status,
    headers: result.headers,
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
