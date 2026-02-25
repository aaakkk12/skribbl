import { NextRequest, NextResponse } from "next/server";

const ACCESS_COOKIE_NAME =
  process.env.NEXT_PUBLIC_ACCESS_COOKIE_NAME || "access_token";

const SESSION_REQUIRED_PREFIXES = ["/rooms", "/room"];
const LEGACY_AUTH_PAGES = ["/login", "/signup", "/reset-password"];

const isStaticAsset = (pathname: string) =>
  pathname.startsWith("/_next/") ||
  pathname.startsWith("/favicon.ico") ||
  pathname.startsWith("/robots.txt") ||
  pathname.startsWith("/sitemap.xml") ||
  /\.[a-zA-Z0-9]+$/.test(pathname);

const pathMatches = (pathname: string, base: string) =>
  pathname === base || pathname.startsWith(`${base}/`);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (isStaticAsset(pathname) || pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  const hasAccessCookie = Boolean(request.cookies.get(ACCESS_COOKIE_NAME)?.value);
  const needsSession = SESSION_REQUIRED_PREFIXES.some((prefix) =>
    pathMatches(pathname, prefix)
  );

  if (needsSession && !hasAccessCookie) {
    const homeUrl = new URL("/", request.url);
    homeUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(homeUrl);
  }

  const isLegacyAuthPage = LEGACY_AUTH_PAGES.some((prefix) => pathMatches(pathname, prefix));
  if (isLegacyAuthPage) {
    return NextResponse.redirect(new URL(hasAccessCookie ? "/rooms" : "/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};
