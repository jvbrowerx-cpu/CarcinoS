/*
 * CarcinoS member activity tracking
 *
 * Records two things for SIGNED-IN members only, on This Week and the Archive:
 *   1. a visit (repeat page loads within 30 minutes count as one visit)
 *   2. a click on a card's "Read paper" link
 *
 * Self-contained: it does not touch the page, its login, its Supabase client or
 * any other script. It reads the existing sign-in from the browser and writes
 * one row to the member_activity table. If anything goes wrong (signed out,
 * expired session, network error, table missing) it silently does nothing, and
 * the page works exactly as before. Removing the <script> line that loads this
 * file switches tracking off completely.
 */
(function () {
  'use strict';
  try {
    var SUPABASE_URL = 'https://kbsingwzbgbdkmhmdaep.supabase.co';
    var SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtic2luZ3d6YmdiZGttaG1kYWVwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA1NzcyMTIsImV4cCI6MjA5NjE1MzIxMn0.NgC1xqY22-q4dLOhsuBb10uPHcnkEP8smSTtcwUqMpY';
    var SESSION_KEY = 'carcinos-auth';          // the key This Week and the Archive already use
    var STATE_KEY = 'carcinos-track-v1';
    var VISIT_GAP_MS = 30 * 60 * 1000;
    var UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

    var path = window.location.pathname || '';
    var page = path.indexOf('/this-week') === 0 ? 'this_week'
             : path.indexOf('/archive') === 0 ? 'archive'
             : null;
    if (!page) return;

    function readSession() {
      try {
        var raw = window.localStorage.getItem(SESSION_KEY);
        if (!raw) return null;
        var s = JSON.parse(raw);
        if (s && s.currentSession) s = s.currentSession;   // older storage shape
        if (!s || !s.access_token || !s.user || !s.user.id) return null;
        if (s.expires_at && s.expires_at * 1000 < Date.now() + 5000) return null;
        return s;
      } catch (e) { return null; }
    }

    function readState() {
      try { return JSON.parse(window.localStorage.getItem(STATE_KEY) || '{}') || {}; }
      catch (e) { return {}; }
    }
    function writeState(st) {
      try { window.localStorage.setItem(STATE_KEY, JSON.stringify(st)); } catch (e) {}
    }
    function newSessionId() {
      return (Date.now().toString(36) + Math.random().toString(36).slice(2, 10)).slice(0, 32);
    }

    function send(fields) {
      var s = readSession();
      if (!s) return;
      try {
        fetch(SUPABASE_URL + '/rest/v1/member_activity', {
          method: 'POST',
          keepalive: true,
          headers: {
            'apikey': SUPABASE_ANON_KEY,
            'Authorization': 'Bearer ' + s.access_token,
            'Content-Type': 'application/json',
            'Prefer': 'return=minimal'
          },
          body: JSON.stringify(fields)
        }).catch(function () {});
      } catch (e) {}
    }

    // ── 1. Visit ─────────────────────────────────────────────────────────────
    // Wait a few seconds so the page's own login code has refreshed the session.
    window.setTimeout(function () {
      try {
        var s = readSession();
        if (!s) return;
        var st = readState();
        var now = Date.now();
        if (st.uid !== s.user.id || !st.last || now - st.last > VISIT_GAP_MS) {
          st = { uid: s.user.id, sid: newSessionId(), last: now };
          writeState(st);
          send({ event_type: 'visit', page: page, session_id: st.sid });
        } else {
          st.last = now;
          writeState(st);
        }
      } catch (e) {}
    }, 4000);

    // ── 2. "Read paper" clicks ───────────────────────────────────────────────
    var lastClick = { key: '', at: 0 };
    document.addEventListener('click', function (ev) {
      try {
        var link = ev.target && ev.target.closest ? ev.target.closest('a.card-source-link') : null;
        if (!link) return;
        var card = link.closest('.card');
        var fields = { event_type: 'read_paper', page: page, session_id: (readState().sid || null) };
        var id = card && card.id && card.id.indexOf('card-') === 0 ? card.id.slice(5) : '';
        if (UUID_RE.test(id)) {
          fields.alert_id = id;                         // This Week cards carry the alert id
        } else {
          var t = card && card.querySelector('.card-title');
          var title = t ? (t.textContent || '').replace(/^\s*Title:\s*/, '').trim() : '';
          if (!title) return;
          fields.card_title = title.slice(0, 500);      // Archive cards: matched by title later
        }
        var key = fields.alert_id || fields.card_title;
        var now = Date.now();
        if (key === lastClick.key && now - lastClick.at < 10000) return;   // ignore double clicks
        lastClick = { key: key, at: now };
        send(fields);
      } catch (e) {}
    }, true);
  } catch (e) {}
})();
