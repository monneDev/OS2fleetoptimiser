import { auth } from "@/lib/auth";
import { headers } from "next/headers";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export async function proxy(req: NextRequest) {
  if (
    req.nextUrl.pathname === "/api/fleet" ||
    req.nextUrl.pathname.startsWith("/api/fleet/")
  ) {
    const backendUrl = new URL(
      process.env.BACKEND_URL ??
        (process.env.NODE_ENV === "development"
          ? "http://localhost:3001"
          : "http://backend:3001"),
    );
    const backendPath = req.nextUrl.pathname.slice("/api/fleet".length);

    backendUrl.pathname = `${backendUrl.pathname.replace(/\/$/, "")}${backendPath || "/"}`;
    backendUrl.search = req.nextUrl.search;

    return NextResponse.rewrite(backendUrl);
  }

  const session = await auth.api.getSession({
    headers: await headers(),
  });

  if (!session) {
    return NextResponse.redirect(new URL("/login?message=notoken", req.url));
  }

  if (process.env.ROLE_CHECK && !session.user.roleValid) {
    return NextResponse.redirect(new URL("/login?message=invalidrole", req.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|login|api/auth).*)",
  ],
};
