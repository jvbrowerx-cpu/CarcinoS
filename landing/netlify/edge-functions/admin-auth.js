// Netlify Edge Function — HTTP Basic Auth gate for the admin portal.
// Runs before the admin page is served. If credentials are missing or wrong,
// the browser shows a native login prompt and the page HTML is never delivered.
//
// Credentials are read from Netlify environment variables (never commit them):
//   ADMIN_USER      — your username
//   ADMIN_PASSWORD  — your password
//
// Set these in Netlify: Site settings → Environment variables → Add variable.

export default async (request, context) => {
  const expectedUser = Netlify.env.get("ADMIN_USER");
  const expectedPass = Netlify.env.get("ADMIN_PASSWORD");

  if (!expectedUser || !expectedPass) {
    return new Response(
      "Admin auth is not configured. Set ADMIN_USER and ADMIN_PASSWORD in Netlify env vars.",
      { status: 500 }
    );
  }

  const authHeader = request.headers.get("authorization");

  if (authHeader && authHeader.startsWith("Basic ")) {
    try {
      const decoded = atob(authHeader.slice(6));
      const idx = decoded.indexOf(":");
      const user = decoded.slice(0, idx);
      const pass = decoded.slice(idx + 1);
      if (user === expectedUser && pass === expectedPass) {
        // Credentials match — let the request continue to the admin page.
        return context.next();
      }
    } catch (_) {
      // Fall through to 401 on malformed header.
    }
  }

  return new Response("Authentication required", {
    status: 401,
    headers: {
      "WWW-Authenticate": 'Basic realm="Admin Area", charset="UTF-8"',
    },
  });
};
