// Netlify Edge Function — per-paper link previews for shared CarcinoS cards.
//
// A shared text holds one link: https://carcino-s.com/s/?c=<alert id>
// iMessage, WhatsApp, Slack etc. read that page's <meta property="og:..."> tags
// to draw the picture card. Those apps don't run JavaScript, so this function
// fills the tags in on the server: paper title, So what, and the paper's
// CarcinoS-style image (made by the weekly pipeline, see share_card.py).
//
// It also embeds the card's data in the page so it shows instantly.
// If anything fails, the page is served unchanged: it still works (it loads
// the card itself) and previews fall back to the generic CarcinoS image.

const SB = "https://kbsingwzbgbdkmhmdaep.supabase.co";
// Public "anon" key — the same one the website already uses in the browser.
const KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtic2luZ3d6YmdiZGttaG1kYWVwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1NzcyMTIsImV4cCI6MjA5NjE1MzIxMn0.NgC1xqY22-q4dLOhsuBb10uPHcnkEP8smSTtcwUqMpY";

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const plain = (s) => String(s ?? "").replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
const clip = (s, n) => (s.length <= n ? s : s.slice(0, n - 1).replace(/\s+\S*$/, "") + "…");

export default async (request, context) => {
  const response = await context.next();
  try {
    const url = new URL(request.url);
    const id = (url.searchParams.get("c") || "").toLowerCase();
    if (!/^[0-9a-f-]{36}$/.test(id)) return response;

    const headers = { apikey: KEY, Authorization: `Bearer ${KEY}` };
    const imgUrl = `${SB}/storage/v1/object/public/share-cards/${id}.png`;
    const [rowsRes, imgRes] = await Promise.all([
      fetch(`${SB}/rest/v1/alerts?id=eq.${id}&status=in.(PUBLISHED,CORRECTED)&select=id,tier,title,summary_json`, { headers }),
      fetch(imgUrl, { method: "HEAD" }).catch(() => null),
    ]);
    if (!rowsRes.ok) return response;
    const rows = await rowsRes.json();
    const row = rows && rows[0];
    if (!row) return response;

    const s = row.summary_json || {};
    const title = plain(row.title) || "An oncology paper";
    const soWhat = plain(s.carcinos_one_liner).replace(/^\*\*?so what[^:]*:\*?\*?\s*/i, "");
    const image = imgRes && imgRes.ok ? imgUrl : `${url.origin}/og-default-share.png`;
    const pageUrl = `${url.origin}/s/?c=${id}`;

    const og = `
<title>${esc(clip(title, 120))} · CarcinoS</title>
<meta name="description" content="${esc(clip(soWhat || "Physician-reviewed oncology updates, shared by a colleague.", 200))}">
<meta property="og:site_name" content="CarcinoS">
<meta property="og:type" content="article">
<meta property="og:url" content="${esc(pageUrl)}">
<meta property="og:title" content="${esc(clip(title, 120))}">
<meta property="og:description" content="${esc(clip(soWhat || "Physician-reviewed oncology updates, shared by a colleague.", 200))}">
<meta property="og:image" content="${esc(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
`;
    // Only the fields the page shows; "<" escaped so the JSON can't close the script tag.
    const card = {
      id: row.id, tier: row.tier, title: row.title,
      summary_json: { carcinos_one_liner: s.carcinos_one_liner || "", disease_site_code: s.disease_site_code || "", sources: (s.sources || []).slice(0, 1) },
    };
    const data = `<script>window.__CARD__=${JSON.stringify(card).replace(/</g, "\\u003c")};</script>`;

    let html = await response.text();
    html = html.replace(/<!--OG-START-->[\s\S]*?<!--OG-END-->/, og).replace("<!--CARD-DATA-->", data);

    const out = new Headers(response.headers);
    out.delete("content-length");
    out.set("content-type", "text/html; charset=utf-8");
    out.set("cache-control", "public, max-age=300");
    return new Response(html, { status: 200, headers: out });
  } catch (_) {
    return response;
  }
};

export const config = { path: ["/s", "/s/"] };
