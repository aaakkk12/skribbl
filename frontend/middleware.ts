import { NextRequest, NextResponse } from "next/server";

const ACCESS_COOKIE_NAME =
  process.env.NEXT_PUBLIC_ACCESS_COOKIE_NAME || "access_token";
const PUBLIC_APP_ORIGIN = (process.env.NEXT_PUBLIC_APP_ORIGIN || "").trim();

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

function normalizeOrigin(raw: string): string {
  return raw.replace(/\/+$/, "");
}

function firstHeaderValue(value: string | null): string {
  return (value || "").split(",")[0].trim();
}

function originFromForwardedHeaders(request: NextRequest): string | null {
  const forwardedHost = firstHeaderValue(request.headers.get("x-forwarded-host"));
  if (!forwardedHost) return null;
  const forwardedProto = firstHeaderValue(request.headers.get("x-forwarded-proto"));
  const proto = forwardedProto || "https";
  return normalizeOrigin(`${proto}://${forwardedHost}`);
}

function originFromHostHeader(request: NextRequest): string | null {
  const host = firstHeaderValue(request.headers.get("host"));
  if (!host) return null;
  const isLocalHost = /^localhost(?::\d+)?$/i.test(host) || /^127\.0\.0\.1(?::\d+)?$/.test(host);
  if (isLocalHost) return null;
  const forwardedProto = firstHeaderValue(request.headers.get("x-forwarded-proto"));
  const proto = forwardedProto || request.nextUrl.protocol.replace(":", "") || "https";
  return normalizeOrigin(`${proto}://${host}`);
}

function resolvePublicOrigin(request: NextRequest): string {
  return (
    originFromForwardedHeaders(request) ||
    originFromHostHeader(request) ||
    (PUBLIC_APP_ORIGIN ? normalizeOrigin(PUBLIC_APP_ORIGIN) : "") ||
    normalizeOrigin(request.nextUrl.origin)
  );
}

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
    const homeUrl = new URL("/", resolvePublicOrigin(request));
    homeUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(homeUrl);
  }

  const isLegacyAuthPage = LEGACY_AUTH_PAGES.some((prefix) => pathMatches(pathname, prefix));
  if (isLegacyAuthPage) {
    return NextResponse.redirect(
      new URL(hasAccessCookie ? "/rooms" : "/", resolvePublicOrigin(request))
    );
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/:path*"],
};
