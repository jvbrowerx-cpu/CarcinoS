/*
 * CarcinoS sign-up source tracking
 *
 * Remembers where a visitor came from (for example a link tagged
 * ?utm_source=acro, a shared card, Twitter or Google) so that, IF they later
 * sign up, the sign-up can be credited to that source.
 *
 * It also counts, anonymously, each time a tagged link is opened (no names,
 * no emails) so the analytics page can show how often shared links are used.
 *
 * Self-contained: it does not touch the page, its sign-up form or any other
 * script. If anything goes wrong it silently does nothing and the page works
 * exactly as before. Removing the <script> line that loads it switches it off.
 *
 * The sign-up form reads the remembered source with CarcinoSSource.get().
 */
(function () {
  'use strict';
  var KEY = 'carcinos-src-v1';
  var OPEN_KEY = 'carcinos-open-v1';
  var KEEP_MS = 90 * 24 * 60 * 60 * 1000;   // remember a source for 90 days
  var SUPABASE_URL = 'https://kbsingwzbgbdkmhmdaep.supabase.co';
  var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtic2luZ3d6YmdiZGttaG1kYWVwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1NzcyMTIsImV4cCI6MjA5NjE1MzIxMn0.NgC1xqY22-q4dLOhsuBb10uPHcnkEP8smSTtcwUqMpY';

  function clean(v, max) {
    return String(v || '').toLowerCase().replace(/[^a-z0-9_.-]+/g, '').slice(0, max || 64);
  }
  function load() {
    try {
      var s = JSON.parse(window.localStorage.getItem(KEY) || 'null');
      if (s && s.source && s.ts && Date.now() - s.ts < KEEP_MS) return s;
    } catch (e) {}
    return null;
  }
  function save(s) {
    try { window.localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }
  function fromReferrer() {
    try {
      if (!document.referrer) return null;
      var host = new URL(document.referrer).hostname.replace(/^www\./, '');
      if (!host || host === window.location.hostname.replace(/^www\./, '')) return null;
      var known = [
        [/(^|\.)t\.co$|twitter\.com$|(^|\.)x\.com$/, 'twitter'],
        [/linkedin\.com$|lnkd\.in$/, 'linkedin'],
        [/instagram\.com$/, 'instagram'],
        [/facebook\.com$|fb\.com$/, 'facebook'],
        [/(^|\.)google\./, 'google'],
        [/bing\.com$/, 'bing'],
        [/duckduckgo\.com$/, 'duckduckgo']
      ];
      for (var i = 0; i < known.length; i++) {
        if (known[i][0].test(host)) return known[i][1];
      }
      return clean(host);
    } catch (e) { return null; }
  }
  function logOpen(s) {
    try {
      // Count each tagged link once per browser per day, so reloads don't inflate it.
      var day = new Date().toISOString().slice(0, 10);
      var id = [s.source, s.medium, s.content, day].join('|');
      var seen = {};
      try { seen = JSON.parse(window.localStorage.getItem(OPEN_KEY) || '{}') || {}; } catch (e) {}
      if (seen[id]) return;
      Object.keys(seen).forEach(function (k) { if (k.slice(-10) !== day) delete seen[k]; });
      seen[id] = 1;
      try { window.localStorage.setItem(OPEN_KEY, JSON.stringify(seen)); } catch (e) {}
      fetch(SUPABASE_URL + '/rest/v1/rpc/record_link_open', {
        method: 'POST',
        keepalive: true,
        headers: {
          'apikey': SUPABASE_ANON_KEY,
          'Authorization': 'Bearer ' + SUPABASE_ANON_KEY,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          p_source: s.source, p_medium: s.medium || null,
          p_content: s.content || null, p_page: window.location.pathname
        })
      }).catch(function () {});
    } catch (e) {}
  }

  try {
    var q = new URLSearchParams(window.location.search);
    var tagged = clean(q.get('utm_source') || q.get('ref'));
    var stored = load();
    if (tagged) {
      var t = {
        source: tagged,
        medium: clean(q.get('utm_medium')),
        content: clean(q.get('utm_content') || q.get('utm_campaign'), 120),
        landing: window.location.pathname,
        referrer: '',
        tagged: true,
        ts: Date.now()
      };
      // A tagged link always wins over an untagged guess; otherwise first visit wins.
      if (!stored || !stored.tagged) save(t);
      logOpen(t);
    } else if (!stored) {
      var ref = fromReferrer();
      var onInvite = window.location.pathname.indexOf('/invite') === 0;
      if (ref || onInvite) {
        save({
          source: ref || 'invite',
          medium: ref ? 'referral' : 'link',
          content: '',
          landing: window.location.pathname,
          referrer: ref || '',
          tagged: false,
          ts: Date.now()
        });
      }
    }
  } catch (e) {}

  window.CarcinoSSource = {
    get: function () {
      var s = load();
      return s || { source: 'direct', medium: '', content: '', landing: '', referrer: '' };
    }
  };
})();
