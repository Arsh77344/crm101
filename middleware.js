import { NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';

const PUBLIC = ['/login', '/auth', '/s/', '/_next', '/favicon'];

export async function middleware(request) {
  let response = NextResponse.next({ request });
  const url = request.nextUrl.pathname;

  if (!process.env.NEXT_PUBLIC_SUPABASE_URL) return response;

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (list) => {
          list.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          list.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        },
      },
    }
  );

  const { data: { user } } = await supabase.auth.getUser();
  const isPublic = PUBLIC.some((p) => url.startsWith(p));

  if (!user && !isPublic) {
    const to = request.nextUrl.clone();
    to.pathname = '/login';
    return NextResponse.redirect(to);
  }
  if (user && url === '/login') {
    const to = request.nextUrl.clone();
    to.pathname = '/';
    return NextResponse.redirect(to);
  }
  return response;
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)'],
};
