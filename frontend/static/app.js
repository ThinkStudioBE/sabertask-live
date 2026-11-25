/* Sabertask Sales: the whole SPA.
   No build step, no framework. Render functions return HTML strings and the
   handlers are delegated from a few roots.

   The one idea that runs through every view: a prospect's industry decides
   which rep owns it, so the industry is never implicit. Every row, card and
   feed item carries its colour and its name, and the industry filter is the
   first control everywhere. */

var state = {
  nav: 'today',
  meta: null,
  segments: [],        // active industry filter
  country: '',
  stage: '',
  owner: '',
  channel: '',
  q: '',
  scope: 'mine',       // Today: mine | team
  pipelineView: 'board',
  clientStatus: 'active',
  leadStatus: 'new',
  leadBrief: '',
  leadSearching: false,
  leadResult: null,   // what the last search reported back
  leadSearchId: null, // looking at one earlier search only
  data: {},
  drawer: null,
  drawerTab: 'overview'
};

/* ------------------------------------------------------------------ utils */

function esc(value) {
  return String(value === null || value === undefined ? '' : value)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* The same lead on Google Maps.

   For a quarter of the leads the register holds no website, and for some of
   those there is nothing to hold: a small cleaning firm with a van and a
   Facebook page. The map listing is where the rest of it lives, opening hours,
   photos, reviews and often the site the register never got, so this is the
   second place to look before judging a fit.

   A plain search URL, no key and no API: name, street and city, which is
   enough to land on the right listing and harmless when it is not. */
function mapsLink(row) {
  var parts = [row.name, row.street, row.city].filter(function (bit) { return bit; });
  var query = encodeURIComponent(parts.join(', '));
  return '<a class="web-link" href="https://www.google.com/maps/search/?api=1&amp;query='
    + query + '" target="_blank" rel="noopener noreferrer"'
    + ' title="Look this one up on Google Maps">Maps'
    + '<span class="web-out" aria-hidden="true">\u2197</span></a>';
}

/* The 50-per-country ceiling, said the way it should be read: a limit of this
   trial, not of the product. One place, because it is claimed on three screens
   and a promise that reads differently in two of them is worse than no promise.

   What the number actually protects is in config.LEAD_CAP_PER_COUNTRY: the open
   map is run by volunteers and a search that pulls thousands of rows is a bad
   neighbour. Lifting it for real means a paid source, not a bigger number. */
function leadCapNote(cap, tail) {
  return 'This trial returns at most ' + (cap || 50) + ' leads per country, '
    + (tail || '') + ' The full version has no cap.';
}

/* A lead's website, as a link that actually opens.

   OpenStreetMap and the business registers both hold the site as people write
   it on a van: "www.anccom.be/", "clean-wise.be". Put that straight into an
   href and the browser reads it as a path on OUR host, so the rep clicks the
   site of a prospect and lands on our own login screen. That is the whole bug:
   the link was there, it just pointed inward. Everything stored without a
   scheme gets https:// here, at the last possible moment, so old rows work
   without touching what is in the database.

   The label is the bare domain, because the rep is scanning a column and
   "https://www." in front of fifty rows tells him nothing. */
function webLink(url, extra) {
  if (!url) return '';
  var full = /^https?:\/\//i.test(url) ? url : 'https://' + url;
  var label = String(url).replace(/^https?:\/\//i, '').replace(/^www\./i, '')
    .replace(/\/+$/, '');
  return '<a class="web-link" href="' + esc(full) + '" target="_blank"'
    + ' rel="noopener noreferrer" title="' + esc(full) + '">'
    + esc(label) + '<span class="web-out" aria-hidden="true">\u2197</span></a>'
    + (extra || '');
}

/* Every amount the API sends is in the base currency. It is converted here, at
   the last possible moment, so switching what you read the pipeline in never
   touches what is stored or what anybody else sees. */
function fx() {
  return (state.meta && state.meta.currency)
    || { per_base: 1, symbol: 'kr' };
}

function money(amount) {
  var rate = fx();
  var whole = Math.round((amount || 0) * rate.per_base);
  return whole.toLocaleString('da-DK').replace(/,/g, '.') + ' ' + rate.symbol;
}

function moneyShort(amount) {
  var rate = fx();
  var n = Math.round((amount || 0) * rate.per_base);
  if (n >= 1000000) return (n / 1000000).toFixed(1).replace('.', ',') + 'M ' + rate.symbol;
  if (n >= 1000) return Math.round(n / 1000) + 'k ' + rate.symbol;
  return n + ' ' + rate.symbol;
}

function api(path, options) {
  options = options || {};
  if (options.body && typeof options.body !== 'string') {
    options.body = JSON.stringify(options.body);
    options.headers = { 'Content-Type': 'application/json' };
  }
  return fetch(path, options).then(function (res) {
    if (res.status === 401) { window.location.href = '/login'; throw new Error('auth'); }
    if (!res.ok) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        throw new Error(data.detail || ('Request failed: ' + res.status));
      });
    }
    return res.status === 204 ? null : res.json();
  });
}

function toast(message) {
  var el = document.getElementById('toast');
  el.textContent = message;
  el.classList.add('on');
  clearTimeout(el._timer);
  el._timer = setTimeout(function () { el.classList.remove('on'); }, 2600);
}

function qs(extra) {
  var parts = [];
  if (state.segments.length) parts.push('segment=' + state.segments.join(','));
  if (state.country) parts.push('country=' + state.country);
  if (state.q) parts.push('q=' + encodeURIComponent(state.q));
  if (extra) parts.push(extra);
  return parts.length ? '?' + parts.join('&') : '';
}

function initials(name) {
  return (name || '?').split(' ').slice(0, 2).map(function (p) { return p[0]; }).join('').toUpperCase();
}

function avatar(user, size) {
  if (!user) return '<span class="avatar" style="background:#cbd5e1">?</span>';
  var style = 'background:' + user.color;
  if (size) style += ';width:' + size + 'px;height:' + size + 'px;flex:0 0 ' + size + 'px';
  return '<span class="avatar" style="' + style + '" title="' + esc(user.name) + '">'
    + esc(user.initials || initials(user.name)) + '</span>';
}

/* The segment chip. Used everywhere; this is the thing that makes a lead's
   industry readable at a glance. */
function segTag(item) {
  if (!item || !item.segment_short) return '';
  return '<span class="seg-tag" style="background:' + item.segment_color + '18;color:'
    + item.segment_color + '"><span class="dot" style="background:'
    + item.segment_color + '"></span>' + esc(item.segment_short) + '</span>';
}

function dueTag(dateString) {
  if (!dateString) return '<span class="due">no date</span>';
  var due = new Date(dateString + 'T00:00:00');
  var today = new Date(); today.setHours(0, 0, 0, 0);
  var days = Math.round((due - today) / 86400000);
  if (days < 0) return '<span class="due over">' + (-days) + 'd late</span>';
  if (days === 0) return '<span class="due today">today</span>';
  if (days === 1) return '<span class="due">tomorrow</span>';
  return '<span class="due">in ' + days + 'd</span>';
}

function stageTag(deal) {
  var cls = ['won', 'lost', 'trial', 'proposal', 'nurture'].indexOf(deal.stage) >= 0 ? ' ' + deal.stage : '';
  return '<span class="stage-tag' + cls + '">' + esc(deal.stage_label) + '</span>';
}

function option(list, value, keyName, labelName) {
  return list.map(function (item) {
    var key = item[keyName || 'key'];
    return '<option value="' + esc(key) + '"' + (String(value) === String(key) ? ' selected' : '') + '>'
      + esc(item[labelName || 'label']) + '</option>';
  }).join('');
}

/* -------------------------------------------------------------- the shell */

var NAV = [
  { key: 'today', label: 'Today', icon: '<path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="9"/>' },
  { key: 'pipeline', label: 'Pipeline', icon: '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="11" rx="1"/><rect x="17" y="4" width="4" height="7" rx="1"/>' },
  { key: 'companies', label: 'Firms', icon: '<path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-5h6v5"/>' },
  { key: 'leads', label: 'Leads', icon: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>' },
  { key: 'clients', label: 'Clients', icon: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>' },
  { key: 'reports', label: 'Reports', icon: '<path d="M3 3v18h18M7 15l4-5 3 3 5-7"/>' },
  { key: 'settings', label: 'Settings', icon: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9c.14.35.37.65.67.86.3.2.65.32 1 .33H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>' }
];

function renderRail() {
  var due = (state.data.today && state.data.today.due_now) || 0;
  var html = '<div class="mark">S</div>';
  NAV.forEach(function (item) {
    var badge = (item.key === 'today' && due) ? '<span class="badge">' + due + '</span>' : '';
    html += '<button data-nav="' + item.key + '" class="' + (state.nav === item.key ? 'on' : '') + '" title="'
      + item.label + '"><svg viewBox="0 0 24 24">' + item.icon + '</svg>'
      + '<span class="label">' + item.label + '</span>' + badge + '</button>';
  });
  html += '<div class="spacer"></div>';
  if (state.meta) {
    html += '<div class="me" style="background:' + state.meta.me.color + '" title="'
      + esc(state.meta.me.name) + '">' + esc(state.meta.me.initials) + '</div>';
    html += '<button data-act="logout" title="Sign out"><svg viewBox="0 0 24 24">'
      + '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/></svg></button>';
  }
  document.getElementById('rail').innerHTML = html;
}

/* The desk strip: which industry sits on whose desk. Clicking one filters
   every view to that industry. */
function renderDesk() {
  if (!state.meta) return;
  var counts = {};
  var source = (state.data.deals && state.data.deals.by_segment)
    || (state.data.companies && state.data.companies.by_segment) || [];
  source.forEach(function (row) { counts[row.segment] = row.count; });

  var html = '<span class="desk-label">Industry desks</span>';
  state.meta.segment_desk.forEach(function (row) {
    var on = state.segments.indexOf(row.segment) >= 0;
    var count = counts[row.segment];
    var seg = (state.meta.segments || []).filter(function (x) { return x.key === row.segment; })[0];
    html += '<button class="desk-pill' + (on ? ' on' : '') + '" data-seg="' + row.segment + '"'
      + (seg && seg.profile ? ' title="' + esc(seg.label + ' \u2014 ' + seg.profile) + '"' : '') + '>'
      + '<span class="dot" style="background:' + row.color + '"></span>'
      + '<span class="seg">' + esc(row.short) + '</span>'
      + '<span class="rep">' + esc(row.owner ? row.owner.name.split(' ')[0] : 'unassigned') + '</span>'
      + (count !== undefined ? '<span class="n">' + count + '</span>' : '')
      + '</button>';
  });
  if (state.segments.length) {
    html += '<button class="btn ghost sm" data-seg="">Clear</button>';
  }
  document.getElementById('desk').innerHTML = html;
}

function segFilter() {
  if (!state.meta) return '';
  var html = '<div class="seg-filter">';
  state.meta.segments.forEach(function (seg) {
    var on = state.segments.indexOf(seg.key) >= 0;
    html += '<button class="seg-chip' + (on ? ' on' : '') + '" data-seg="' + seg.key + '"'
      + (seg.profile ? ' title="' + esc(seg.label + ' \u2014 ' + seg.profile) + '"' : '')
      + (on ? ' style="background:' + seg.color + '"' : '') + '>'
      + '<span class="dot" style="background:' + seg.color + '"></span>' + esc(seg.short) + '</button>';
  });
  return html + '</div><span class="divider"></span>';
}

// What each industry means, in Sabertask's own words. It sits on an empty
// Leads tab because that is the moment a rep has to decide what to type, and
// an industry name alone does not say who is behind it. The text is read off
// sabertask.com and lives in config.SEGMENTS, not here.
function segProfiles() {
  if (!state.meta || !state.meta.segments) return '';
  var ideal = state.meta.ideal_client;
  return '<div class="seg-profiles">'
    + '<div class="seg-profiles-head">Who we are looking for</div>'
    + (ideal && ideal.note
        ? '<div class="seg-profiles-ideal">' + esc(ideal.note)
          + '<span>' + esc(ideal.source || '') + '</span>'
          // The customers the profile was read off. They are named here and
          // nowhere else in the app: they are not prospects and must never
          // turn up in a pipeline or a mail queue.
          + ((ideal.examples || []).length
              ? '<span class="seg-profiles-eg">Read off: '
                + ideal.examples.map(function (eg) {
                    return esc(eg[0]) + ' (' + esc(eg[1]) + ', ' + eg[2] + ')';
                  }).join(' &middot; ')
                + '</span>'
              : '')
          + '</div>'
        : '')
    + state.meta.segments.filter(function (seg) { return seg.profile; })
        .map(function (seg) {
          return '<div class="seg-profile">'
            + '<div class="seg-profile-name"><span class="dot" style="background:'
            + seg.color + '"></span>' + esc(seg.label) + '</div>'
            + '<div class="seg-profile-text">' + esc(seg.profile) + '</div>'
            + (seg.pain
                ? '<div class="seg-profile-pain">' + esc(seg.pain) + '</div>'
                : '')
            + '</div>';
        }).join('')
    + '</div>';
}

function countrySelect() {
  return '<select data-filter="country"><option value="">All countries</option>'
    + option(state.meta.countries, state.country) + '</select>';
}

function ownerSelect() {
  return '<select data-filter="owner"><option value="">All reps</option>'
    + state.meta.team.map(function (user) {
      return '<option value="' + user.id + '"' + (String(state.owner) === String(user.id) ? ' selected' : '')
        + '>' + esc(user.name) + '</option>';
    }).join('') + '</select>';
}

/* ------------------------------------------------------------------ TODAY */

var GROUP_TITLES = {
  overdue: 'Overdue', today: 'Today', week: 'This week',
  later: 'Later', no_date: 'No date'
};

function viewToday() {
  var data = state.data.today;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';

  var html = '<div class="kpis">'
    + '<div class="kpi accent"><div class="k">Needs you now</div><div class="v">' + data.due_now
    + '</div><div class="sub">' + data.counts.overdue + ' overdue, ' + data.counts.today + ' due today</div></div>'
    + '<div class="kpi"><div class="k">This week</div><div class="v">' + data.counts.week + '</div></div>'
    + '<div class="kpi"><div class="k">Later</div><div class="v">' + data.counts.later + '</div></div>'
    + '<div class="kpi"><div class="k">No date</div><div class="v">' + data.counts.no_date
    + '</div><div class="sub">steps nobody has dated</div></div>'
    + '</div>';

  html += '<div class="filterbar">' + segFilter()
    + '<select data-filter="scope">'
    + '<option value="mine"' + (state.scope === 'mine' ? ' selected' : '') + '>My desk</option>'
    + '<option value="team"' + (state.scope === 'team' ? ' selected' : '') + '>Whole team</option>'
    + '</select>'
    + '<button class="btn sm" data-act="new-task">+ Task</button></div>';

  html += '<div class="view">';
  var any = false;
  ['overdue', 'today', 'week', 'later', 'no_date'].forEach(function (key) {
    var items = data.groups[key];
    if (!items.length) return;
    any = true;
    html += '<div class="feed-group"><h2 style="margin-top:0">' + GROUP_TITLES[key]
      + ' <span class="count-pill">' + items.length + '</span></h2>';
    items.forEach(function (item) {
      html += '<div class="feed-item">'
        + '<div class="seg-bar" style="background:' + (item.segment_color || '#cbd5e1') + '"></div>'
        + '<div class="body" data-open-deal="' + (item.deal_id || '') + '" data-open-client="' + (item.client_id || '') + '">'
        + '<div class="t">' + esc(item.title) + '</div>'
        + '<div class="m">' + segTag(item)
        + '<strong>' + esc(item.company || '') + '</strong>'
        + (item.stage_label ? '<span>' + esc(item.stage_label) + '</span>' : '')
        + (item.mrr ? '<span>' + money(item.mrr) + ' / mo</span>' : '')
        + '<span class="kind-tag">' + esc(item.kind_label) + '</span>'
        + '</div></div>'
        + '<div class="right">' + (item.owner ? avatar(item.owner) : '') + dueTag(item.due_date)
        + '<button class="tick" data-complete="' + esc(item.id) + '" title="Done">'
        + '<svg viewBox="0 0 24 24"><path d="M4 12l6 6L20 6"/></svg></button>'
        + '</div></div>';
    });
    html += '</div>';
  });
  if (!any) html += '<div class="empty">Nothing waiting. Either a very good day or a very quiet one.</div>';
  return html + '</div>';
}

/* --------------------------------------------------------------- PIPELINE */

function viewPipeline() {
  var data = state.data.deals;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';
  var totals = data.totals;

  var html = '<div class="kpis">'
    + '<div class="kpi accent"><div class="k">Open pipeline</div><div class="v">' + money(totals.mrr)
    + '</div><div class="sub">' + totals.count + ' deals, monthly recurring</div></div>'
    + '<div class="kpi"><div class="k">Weighted</div><div class="v">' + money(totals.weighted)
    + '</div><div class="sub">by stage probability</div></div>'
    + '<div class="kpi"><div class="k">Contract value</div><div class="v">' + moneyShort(totals.acv)
    + '</div><div class="sub">over the full terms</div></div>';

  // Per-industry subtotals: the number each desk is measured on.
  (data.by_segment || []).slice(0, 3).forEach(function (row) {
    html += '<div class="kpi" style="border-left:4px solid ' + row.color + '">'
      + '<div class="k">' + esc(row.short) + '</div><div class="v">' + moneyShort(row.mrr)
      + '</div><div class="sub">' + row.count + ' deals</div></div>';
  });
  html += '</div>';

  html += '<div class="filterbar">' + segFilter() + countrySelect() + ownerSelect()
    + '<select data-filter="channel"><option value="">All sources</option>'
    + option(state.meta.channels, state.channel) + '</select>'
    + '<span class="divider"></span>'
    + '<button class="btn sm' + (state.pipelineView === 'board' ? ' primary' : '') + '" data-view="board">Board</button>'
    + '<button class="btn sm' + (state.pipelineView === 'list' ? ' primary' : '') + '" data-view="list">List</button>'
    + '<span class="divider"></span>'
    + '<button class="btn sm" data-act="mail-draft-all" title="Write a first mail for every deal '
    + 'that has none yet. Each one is still read and sent by hand, on the deal itself.">'
    + 'Draft every open mail</button>'
    + '</div>';

  return html + (state.pipelineView === 'board' ? boardHtml(data) : dealListHtml(data));
}

function boardHtml(data) {
  var byStage = {};
  data.deals.forEach(function (deal) {
    (byStage[deal.stage] = byStage[deal.stage] || []).push(deal);
  });
  var stages = state.meta.board_stages.concat(['nurture', 'lost']);

  var html = '<div class="board">';
  stages.forEach(function (key) {
    var list = byStage[key] || [];
    var stage = state.meta.stages.concat(state.meta.extra_stages)
      .filter(function (s) { return s.key === key; })[0] || {};
    var label = stage.label || key;
    var sum = list.reduce(function (total, deal) { return total + deal.mrr; }, 0);
    html += '<div class="col" data-stage="' + key + '">'
      + '<h3' + (stage.hint ? ' title="' + esc(stage.hint) + '"' : '') + '>'
      + '<span>' + esc(label) + ' <span class="count-pill">' + list.length + '</span></span>'
      + '<span class="col-mrr">' + moneyShort(sum) + '</span></h3>';
    list.forEach(function (deal) {
      html += '<div class="deal-card" draggable="true" data-deal="' + deal.id + '">'
        + '<div class="seg-bar" style="background:' + deal.segment_color + '"></div>'
        + '<div class="body">'
        + '<div class="title">' + esc(deal.company)
        + (deal.draft_waiting ? ' <span class="mail-dot" title="A mail is written and waiting">'
          + '\u2709</span>' : '') + '</div>'
        + '<div class="row">' + segTag(deal)
        + '<span class="meta">' + esc(deal.flag) + ' ' + esc(deal.city || '') + '</span></div>'
        + '<div class="row"><span class="mrr">' + money(deal.mrr) + '</span>'
        + '<span class="meta">/ mo &middot; ' + deal.seats + ' users</span></div>'
        + '<div class="row">' + (deal.owner ? avatar(deal.owner) : '')
        + (deal.next_action ? dueTag(deal.next_action_date) : '')
        + (deal.trial_day !== null && deal.trial_day !== undefined
          ? '<span class="meta">trial day ' + deal.trial_day + '</span>' : '')
        + '</div></div></div>';
    });
    if (!list.length) html += '<div style="padding:14px;color:#94a3b8;font-size:12px">Empty</div>';
    html += '</div>';
  });
  return html + '</div>';
}

function dealListHtml(data) {
  var html = '<div class="view"><div class="list-wrap"><table class="list"><thead><tr>'
    + '<th>Industry</th><th>Company</th><th>Stage</th><th>Next step</th>'
    + '<th>Owner</th><th class="num">Users</th><th class="num">MRR</th></tr></thead><tbody>';
  data.deals.forEach(function (deal) {
    html += '<tr data-deal="' + deal.id + '">'
      + '<td><div class="seg-cell"><div class="seg-stripe" style="background:' + deal.segment_color
      + '"></div>' + segTag(deal) + '</div></td>'
      + '<td><div class="co-name">' + esc(deal.company)
      + (deal.draft_waiting ? ' <span class="mail-dot" title="A mail is written and waiting">'
        + '\u2709</span>' : '') + '</div>'
      + '<div class="co-sub">' + esc(deal.flag) + ' ' + esc(deal.city || '') + ' &middot; '
      + esc(deal.channel_label) + '</div></td>'
      + '<td>' + stageTag(deal) + '<div class="co-sub">' + deal.days_in_stage + 'd in stage</div></td>'
      + '<td>' + (deal.next_action
        ? esc(deal.next_action) + ' ' + dueTag(deal.next_action_date)
        : '<span style="color:#94a3b8">nothing planned</span>') + '</td>'
      + '<td><div class="owner-cell">' + avatar(deal.owner)
      + '<span>' + esc(deal.owner ? deal.owner.name.split(' ')[0] : '') + '</span></div></td>'
      + '<td class="num">' + deal.seats + '</td>'
      + '<td class="num"><strong>' + money(deal.mrr) + '</strong></td></tr>';
  });
  if (!data.deals.length) html += '<tr><td colspan="7"><div class="empty">No deals match this filter.</div></td></tr>';
  return html + '</tbody></table></div></div>';
}

/* -------------------------------------------------------------- COMPANIES */

function viewCompanies() {
  var data = state.data.companies;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';

  var html = '<div class="kpis">';
  data.by_segment.forEach(function (row) {
    html += '<div class="kpi" style="border-left:4px solid ' + row.color + '">'
      + '<div class="k">' + esc(row.short) + '</div><div class="v">' + row.count
      + '</div><div class="sub">' + moneyShort(row.mrr) + ' open</div></div>';
  });
  html += '</div>';

  html += '<div class="filterbar">' + segFilter() + countrySelect() + ownerSelect()
    + '<button class="btn sm" data-act="new-company">+ Company</button></div>';

  html += '<div class="view"><div class="list-wrap"><table class="list"><thead><tr>'
    + '<th>Industry</th><th>Company</th><th>Field staff</th><th>Runs today</th>'
    + '<th>Stage</th><th>Owner</th><th class="num">Open MRR</th></tr></thead><tbody>';
  data.companies.forEach(function (company) {
    html += '<tr data-company="' + company.id + '">'
      + '<td><div class="seg-cell"><div class="seg-stripe" style="background:' + company.segment_color
      + '"></div>' + segTag(company) + '</div></td>'
      + '<td><div class="co-name">' + esc(company.name)
      + (company.is_client ? ' <span class="stage-tag won">client</span>' : '') + '</div>'
      + '<div class="co-sub">' + esc(company.flag) + ' ' + esc(company.city || '') + '</div></td>'
      + '<td>' + (company.field_staff || '-') + '<div class="co-sub">'
      + (company.sites ? company.sites + ' sites' : '') + '</div></td>'
      + '<td style="max-width:180px"><div class="co-sub" style="margin:0">'
      + esc(company.current_tool || '-') + '</div></td>'
      + '<td>' + (company.stage_label ? '<span class="stage-tag">' + esc(company.stage_label) + '</span>' : '-') + '</td>'
      + '<td><div class="owner-cell">' + avatar(company.owner)
      + '<span>' + esc(company.owner ? company.owner.name.split(' ')[0] : '') + '</span></div></td>'
      + '<td class="num"><strong>' + money(company.open_mrr) + '</strong></td></tr>';
  });
  if (!data.companies.length) html += '<tr><td colspan="7"><div class="empty">Nothing here.</div></td></tr>';
  return html + '</tbody></table></div></div>';
}

/* ---------------------------------------------------------------- CLIENTS */

/* --------------------------------------------------------------- SETTINGS */

/* Two settings, and they are different kinds of thing. The countries belong to
   the installation and decide where a search may look: add one here and the
   next search can use it, which is the point. The currency belongs to the
   person reading the screen and changes nothing anybody else sees. */
function viewSettings() {
  var data = state.data.settings;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';
  var cur = data.currency;

  var html = '<div class="view">';

  html += '<div class="panel" style="margin-bottom:14px">'
    + '<h3 style="margin:0 0 4px">Countries to search</h3>'
    + '<div class="co-sub" style="margin-bottom:14px">A search looks only in '
    + 'these. Add one and it works straight away, no restart and nothing to '
    + 'deploy. '
    + leadCapNote(data.lead_cap_per_country,
        'counted over every industry in that search, so the total grows with '
        + 'the number of countries you pick.')
    + '</div>'
    + '<div class="set-chips">';
  data.countries.forEach(function (row) {
    html += '<span class="set-chip">' + esc(row.flag) + ' ' + esc(row.label)
      + ' <span class="co-sub" style="margin:0">' + esc(row.key) + '</span>'
      + (row.in_use ? '<span class="chip-count">' + row.in_use + '</span>' : '')
      + (row.register
          ? '<span class="chip-reg" title="Searched in the official business '
            + 'register">' + esc(row.register) + '</span>'
          : '')
      + '<button class="chip-x" data-act="country-remove" data-code="' + esc(row.key)
      + '" title="Remove ' + esc(row.label) + '">&times;</button></span>';
  });
  html += '</div>'
    + '<div class="set-add">'
    + '<input id="c-code" class="set-inp" style="max-width:90px" placeholder="IE" maxlength="2">'
    + '<input id="c-name" class="set-inp" placeholder="Ireland">'
    + '<button class="btn primary sm" data-act="country-add">Add country</button>'
    + '</div>'
    + '<div class="co-sub">Two-letter country code. Records already found in a '
    + 'country stay when you remove it: they are real companies.</div>'
    + '</div>';

  html += '<div class="panel">'
    + '<h3 style="margin:0 0 4px">Your reporting currency</h3>'
    + '<div class="co-sub" style="margin-bottom:14px">Everything is stored in '
    + esc(cur.base) + ' and converted for you here, so your colleagues keep '
    + 'reading the same pipeline in theirs.</div>'
    + '<div class="set-chips">';
  cur.options.forEach(function (option) {
    html += '<button class="set-chip' + (option.key === cur.current ? ' on' : '')
      + '" data-act="currency" data-code="' + esc(option.key) + '">'
      + esc(option.label) + ' <span class="co-sub" style="margin:0">'
      + esc(option.symbol) + '</span></button>';
  });
  html += '</div>'
    + '<div class="co-sub">Rates are fixed for the trial, as of '
    + esc(cur.as_of) + '. They are not live.</div>'
    + '</div>';

  return html + '</div>';
}

/* ------------------------------------------------------------- FIND LEADS */

/* A brief in plain words, then real companies off the map: name, address,
   website and phone as OpenStreetMap holds them. Nothing here touches the
   pipeline until a rep says so, because a search turns up names nobody has
   looked at yet and the floor's numbers should not move because a search ran. */
function viewLeads() {
  var data = state.data.leads;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';
  var counts = data.counts;

  var html = '<div class="kpis">'
    + '<div class="kpi accent"><div class="k">To review</div><div class="v">' + counts.new
    + '</div><div class="sub">found, not judged yet</div></div>'
    + '<div class="kpi"><div class="k">In the pipeline</div><div class="v">' + counts.added + '</div></div>'
    + '<div class="kpi"><div class="k">Dismissed</div><div class="v">' + counts.dismissed + '</div></div>'
    + '</div>';

  html += '<div class="view">';

  html += '<div class="lead-brief">'
    + '<label class="mail-label">What are you looking for?</label>'
    + '<div class="lead-brief-row">'
    + '<input id="lead-brief" class="mail-input" style="margin:0"'
    + ' placeholder="cleaning companies in Antwerp and Rotterdam with their own crews"'
    + ' value="' + esc(state.leadBrief) + '"' + (state.leadSearching ? ' disabled' : '') + '>'
    + '<button class="btn primary" data-act="lead-search"' + (state.leadSearching ? ' disabled' : '')
    + '>' + (state.leadSearching ? 'Searching' : 'Search') + '</button>'
    + '</div>'
    + '<div class="co-sub">Name an industry and a city or a country. '
    + 'Countries with an official business register are searched there and the '
    + 'rest off the open map. '
    + leadCapNote(data.cap_per_country, 'across all industries in that search.')
    + '</div>';
  if (state.leadResult) {
    var r = state.leadResult;
    html += '<div class="lead-result">' + r.shown + ' on the list for '
      + esc((r.criteria.segments || []).join(', ')) + ' in '
      + esc((r.criteria.cities || []).join(', '))
      + (r.already_known ? ' &middot; ' + r.already_known + ' already known' : '')
      + (r.capped
          ? ' &middot; there were more: the trial stops at ' + r.limit
            + ' per country'
          : '')
      + ((r.skipped && r.skipped.length)
          ? ' &middot; not reached in time: ' + esc(r.skipped.join(', '))
          : '')
      + '</div>';
    // Where each country's answer came from. The official register and the map
    // do not hold the same companies, so two searches that look alike can be
    // reading different sources, and a rep should be able to see which.
    if (r.sources && r.sources.length) {
      html += '<div class="lead-sources">' + r.sources.map(function (row) {
        return '<span class="lead-src' + (row.source === 'map' ? ' map' : '') + '">'
          + esc(row.country) + ': '
          + esc(row.source === 'map' ? 'open map' : row.source) + '</span>';
      }).join('') + '</div>';
    }
  }
  html += '</div>';

  // While a search runs, the middle of the screen says so. Anything else there
  // reads as the answer, and "nothing waiting" under a spinning button is the
  // one message a search must not give.
  if (state.leadSearching) {
    return html + '<div class="lead-searching">'
      + '<div class="spinner"></div>'
      + '<div class="lead-searching-main">Searching</div>'
      + '<div class="co-sub">' + esc(state.leadBrief) + '</div>'
      + '<div class="co-sub">Reading the brief, then looking the companies up. '
      + 'This takes a few seconds.</div>'
      + '</div>' + searchHistory() + '</div>';
  }

  html += searchHistory();

  html += '<div class="filterbar">' + segFilter()
    + (state.leadSearchId
        ? '<button class="btn sm" data-act="lead-all-searches">Every search &times;</button>'
        : '')
    + '<select data-filter="leadStatus">'
    + '<option value="new"' + (state.leadStatus === 'new' ? ' selected' : '') + '>To review</option>'
    + '<option value="added"' + (state.leadStatus === 'added' ? ' selected' : '') + '>In the pipeline</option>'
    + '<option value="dismissed"' + (state.leadStatus === 'dismissed' ? ' selected' : '') + '>Dismissed</option>'
    + '</select>'
    // Only offered on the review list, and it says how many it will take, so
    // nobody clicks it wondering what "all" covers.
    + (state.leadStatus === 'new' && data.rows.length
        ? '<button class="btn primary sm" data-act="lead-add-all">Add all '
          + data.rows.length + '</button>'
        : '')
    + '</div>';

  if (!data.rows.length) {
    return html + '<div class="empty">'
      + (state.leadStatus === 'new'
          ? 'Nothing waiting. Describe what you are after and search.'
          : 'Nothing here yet.') + '</div>'
      + (state.leadStatus === 'new' ? segProfiles() : '') + '</div>';
  }

  html += '<div class="list-wrap"><table class="list"><thead><tr>'
    + '<th>Industry</th><th>Company</th><th>Where</th><th>Staff</th><th>Contact</th>'
    + '<th class="num">Fit</th><th></th></tr></thead><tbody>';
  data.rows.forEach(function (row) {
    html += '<tr>'
      + '<td><div class="seg-cell"><div class="seg-stripe" style="background:'
      + row.segment_color + '"></div>' + segTag(row) + '</div></td>'
      + '<td><div class="co-name">' + esc(row.name) + '</div>'
      + '<div class="co-sub">'
      + (row.website ? webLink(row.website) : 'no website on file')
      + ' <span class="sub-sep">&middot;</span> ' + mapsLink(row)
      + '</div></td>'
      + '<td>' + esc(row.flag) + ' ' + esc(row.city || '')
      + '<div class="co-sub">' + esc(row.street || '') + '</div></td>'
      + '<td>' + (row.field_staff ? row.field_staff : '-')
      + '<div class="co-sub">in the field</div></td>'
      + '<td><div class="co-sub" style="margin:0">' + esc(row.phone || '')
      + (row.email ? '<br>' + esc(row.email) : '') + '</div></td>'
      + '<td class="num"><strong>' + row.score + '</strong></td>'
      + '<td class="num">' + (row.status === 'new'
          ? '<button class="btn sm" data-act="lead-dismiss" data-id="' + row.id + '">Not a fit</button> '
            + '<button class="btn primary sm" data-act="lead-add" data-id="' + row.id + '">Add</button>'
          : '<span class="stage-tag' + (row.status === 'added' ? ' won' : ' nurture') + '">'
            + (row.status === 'added' ? 'in the pipeline' : 'dismissed') + '</span>')
      + '</td></tr>';
  });
  return html + '</tbody></table></div></div>';
}

/* Every brief that has been run, so two reps do not go looking for the same
   thing a week apart. The industry chips are the point: a search is read by
   what it was after, not by its wording. */
function searchHistory() {
  var rows = (state.data.leadSearches && state.data.leadSearches.searches) || [];
  if (!rows.length) return '';
  var html = '<div class="lead-history"><div class="lead-history-head">Earlier searches</div>';
  rows.forEach(function (row) {
    html += '<div class="lead-past' + (state.leadSearchId === row.id ? ' on' : '')
      + '" data-search="' + row.id + '">'
      + '<div class="lead-past-main"><div class="lead-past-brief">' + esc(row.brief) + '</div>'
      + '<div class="lead-past-tags">'
      + row.segments.map(function (seg) {
          return '<span class="seg-tag" style="background:' + seg.color + '1f;color:'
            + seg.color + '">' + esc(seg.short) + '</span>';
        }).join(' ')
      + (row.cities.length ? '<span class="co-sub" style="margin:0">' + esc(row.cities.join(', ')) + '</span>' : '')
      + '</div></div>'
      + '<div class="lead-past-count">' + row.kept + ' found'
      + (row.added ? '<div class="co-sub">' + row.added + ' added</div>' : '')
      + '</div></div>';
  });
  return html + '</div>';
}

/* -------------------------------------------------------------- COLD MAIL */

/* The mail no longer has a screen of its own: it is a tab on the deal, so the
   rep writes it on the card he is already working. mailState paints the state
   on that tab, mailEditor is the mail itself. Both are fed by
   GET /api/mail/{deal_id}, fetched together with the deal. */
/* The Mail tab acts on whichever deal the drawer is showing. After a change the
   deal is reopened on the same tab, and the board behind it is reloaded so the
   waiting-mail marker on the card follows along. */
function mailDeal() {
  return state.drawer && state.drawer.kind === 'deal' ? state.drawer.data.deal.id : null;
}

function afterMail() {
  var id = mailDeal();
  if (id) openDeal(id, true);
  load();
}

function mailState(row) {
  var map = {
    none: ['stage-tag', 'to write'], draft: ['stage-tag trial', 'drafted'],
    sent: ['stage-tag won', 'sent'], skipped: ['stage-tag nurture', 'skipped']
  };
  var pair = map[row.status] || map.none;
  return '<span class="' + pair[0] + '">' + pair[1] + '</span>';
}

function mailEditor(row) {
  var html = '<div class="mail-head">'
    + '<div><div class="mail-to">To ' + (row.to_name ? esc(row.to_name) : 'nobody yet')
    + '</div><div class="co-sub">' + (row.to_email ? esc(row.to_email) : 'This prospect has no contact mailbox, so it cannot go out.')
    + '</div></div>'
    + '<div style="text-align:right">' + mailState(row)
    + '<div class="mail-why">' + esc(row.field_staff || 0) + ' field staff &middot; runs '
    + esc(row.current_tool || 'nothing we know of') + '</div></div></div>';

  if (row.status === 'skipped') {
    html += '<div class="mail-skipped">Skipped: ' + esc(row.skipped_reason || '')
      + '. Drafting again puts it back on the list.</div>';
  }

  if (!row.subject) {
    html += '<div class="empty">No draft yet. The industry, the crew size and what '
      + 'they run today are already on file, so the first mail writes itself.</div>';
  } else {
    html += '<label class="mail-label">Subject</label>'
      + '<input id="mail-subject" class="mail-input" value="' + esc(row.subject) + '"'
      + (row.status === 'sent' ? ' disabled' : '') + '>'
      + '<label class="mail-label">Mail</label>'
      + '<textarea id="mail-body" class="mail-body"' + (row.status === 'sent' ? ' disabled' : '')
      + '>' + esc(row.body) + '</textarea>'
      + (row.sent_at ? '<div class="co-sub">Sent ' + esc(row.sent_at.slice(0, 10)) + '</div>' : '');
  }

  html += '<div class="mail-actions">';
  if (row.status !== 'sent') {
    html += '<button class="btn sm" data-act="mail-draft">'
      + (row.subject ? 'Write it again' : 'Draft the mail') + '</button>';
  }
  if (row.subject) {
    html += '<button class="btn sm" data-act="mail-copy">Copy</button>';
  }
  if (row.subject && row.status !== 'sent') {
    html += '<button class="btn sm" data-act="mail-save">Save edits</button>'
      + '<button class="btn primary sm" data-act="mail-sent"'
      + (row.to_email ? '' : ' disabled') + '>I sent this</button>';
  }
  if (row.status !== 'sent' && row.status !== 'skipped') {
    html += '<button class="btn sm" data-act="mail-skip">Do not write</button>';
  }
  html += '</div>';
  html += '<div class="mail-note">The mail goes out from your own mailbox. '
    + '"I sent this" logs the touch and moves the deal on.</div>';
  return html;
}

function viewClients() {
  var data = state.data.clients;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';
  var stats = data.stats;

  var html = '<div class="kpis">'
    + '<div class="kpi accent"><div class="k">Live MRR</div><div class="v">' + money(stats.mrr)
    + '</div><div class="sub">' + money(stats.arr) + ' a year</div></div>'
    + '<div class="kpi"><div class="k">Clients</div><div class="v">' + stats.count
    + '</div><div class="sub">' + stats.seats + ' users live</div></div>'
    + '<div class="kpi"><div class="k">Check-in due</div><div class="v">' + stats.due_now + '</div></div>'
    + '<div class="kpi"><div class="k">At risk</div><div class="v">' + stats.at_risk
    + '</div><div class="sub">' + stats.watch + ' on watch</div></div>'
    + '<div class="kpi"><div class="k">Retention</div><div class="v">' + stats.retention + '%'
    + '</div><div class="sub">' + stats.churned + ' churned</div></div>'
    + '</div>';

  html += '<div class="filterbar">' + segFilter()
    + '<select data-filter="clientStatus">'
    + '<option value="active"' + (state.clientStatus === 'active' ? ' selected' : '') + '>Active</option>'
    + '<option value="churned"' + (state.clientStatus === 'churned' ? ' selected' : '') + '>Churned</option>'
    + '<option value="all"' + (state.clientStatus === 'all' ? ' selected' : '') + '>All</option>'
    + '</select></div>';

  html += '<div class="view"><div class="list-wrap"><table class="list"><thead><tr>'
    + '<th>Industry</th><th>Client</th><th>Health</th><th>Next check-in</th>'
    + '<th>Live since</th><th>Owner</th><th class="num">MRR</th></tr></thead><tbody>';
  data.clients.forEach(function (client) {
    html += '<tr data-client="' + client.id + '">'
      + '<td><div class="seg-cell"><div class="seg-stripe" style="background:' + client.segment_color
      + '"></div>' + segTag(client) + '</div></td>'
      + '<td><div class="co-name">' + esc(client.company) + '</div>'
      + '<div class="co-sub">' + esc(client.flag) + ' ' + esc(client.city || '') + ' &middot; '
      + client.seats + ' users</div></td>'
      + '<td><span class="health" style="background:' + client.health_color + '"></span> '
      + esc(client.health_label) + '</td>'
      + '<td>' + (client.status === 'churned'
        ? '<span class="stage-tag lost">churned</span>' : dueTag(client.next_meeting_date)) + '</td>'
      + '<td>' + client.months_live + ' months</td>'
      + '<td><div class="owner-cell">' + avatar(client.owner)
      + '<span>' + esc(client.owner ? client.owner.name.split(' ')[0] : '') + '</span></div></td>'
      + '<td class="num"><strong>' + money(client.mrr) + '</strong></td></tr>';
  });
  if (!data.clients.length) html += '<tr><td colspan="7"><div class="empty">No clients in this view.</div></td></tr>';
  return html + '</tbody></table></div></div>';
}

/* ---------------------------------------------------------------- REPORTS */

function viewReports() {
  var data = state.data.reports;
  if (!data) return '<div class="view"><div class="empty">Loading</div></div>';
  var head = data.headline;

  var html = '<div class="kpis">'
    + '<div class="kpi accent"><div class="k">Open pipeline</div><div class="v">' + money(head.open_mrr)
    + '</div><div class="sub">' + head.open_count + ' deals</div></div>'
    + '<div class="kpi"><div class="k">Weighted</div><div class="v">' + money(head.weighted) + '</div></div>'
    + '<div class="kpi"><div class="k">Live MRR</div><div class="v">' + money(head.live_mrr)
    + '</div><div class="sub">' + head.won_count + ' deals won</div></div>'
    + '<div class="kpi"><div class="k">Win rate</div><div class="v">'
    + (head.win_rate === null ? '-' : head.win_rate + '%') + '</div></div>'
    + '<div class="kpi"><div class="k">Days to win</div><div class="v">'
    + (head.avg_days_to_win === null ? '-' : head.avg_days_to_win) + '</div><div class="sub">average</div></div>'
    + '</div>';

  html += '<div class="view"><div class="cards-grid">';

  // The industry table first: this is the split the floor is organised around.
  html += '<div class="panel wide"><h3>By industry, and whose desk it is on</h3>'
    + '<table class="list"><thead><tr><th>Industry</th><th>Owner</th><th class="num">Open</th>'
    + '<th class="num">Open MRR</th><th class="num">Weighted</th><th class="num">Won</th>'
    + '<th class="num">Won MRR</th><th class="num">Win rate</th></tr></thead><tbody>';
  data.by_segment.forEach(function (row) {
    html += '<tr style="cursor:default">'
      + '<td><div class="seg-cell"><div class="seg-stripe" style="background:' + row.color + '"></div>'
      + '<strong>' + esc(row.label) + '</strong></div></td>'
      + '<td><div class="owner-cell">' + avatar(row.owner)
      + '<span>' + esc(row.owner ? row.owner.name : 'unassigned') + '</span></div></td>'
      + '<td class="num">' + row.open_count + '</td>'
      + '<td class="num"><strong>' + money(row.open_mrr) + '</strong></td>'
      + '<td class="num">' + money(row.weighted) + '</td>'
      + '<td class="num">' + row.won_count + '</td>'
      + '<td class="num">' + money(row.won_mrr) + '</td>'
      + '<td class="num">' + (row.win_rate === null ? '-' : row.win_rate + '%') + '</td></tr>';
  });
  html += '</tbody></table></div>';

  // Funnel
  html += '<div class="panel"><h3>Funnel</h3>';
  var top = Math.max.apply(null, data.funnel.map(function (r) { return r.ever_reached; }).concat([1]));
  data.funnel.forEach(function (row) {
    var width = Math.round(100 * row.ever_reached / top);
    html += '<div class="funnel-row"><span class="nm">' + esc(row.label) + '</span>'
      + '<span class="track"><span class="fill" style="width:' + width + '%">'
      + (row.ever_reached || '') + '</span></span>'
      + '<span class="pc" title="Share of everything that ever reached Lead">'
      + row.conversion + '%</span>'
      // The step on its own, which is the number that says where the leak is.
      + '<span class="pc step"'
      + (row.step_conversion === null || row.step_conversion === undefined
          ? '>&middot;'
          : ' title="Of those that reached the stage above">'
            + row.step_conversion + '%')
      + '</span></div>';
  });
  html += '</div>';

  // Team
  html += '<div class="panel"><h3>Team</h3><table class="list"><thead><tr>'
    + '<th>Rep</th><th class="num">Open</th><th class="num">Won MRR</th><th class="num">Win</th>'
    + '</tr></thead><tbody>';
  data.team.forEach(function (row) {
    html += '<tr style="cursor:default"><td><div class="owner-cell">' + avatar(row.user)
      + '<div><div style="font-weight:600">' + esc(row.user.name) + '</div>'
      + '<div style="margin-top:3px;display:flex;gap:4px">'
      + (row.segments.length
        ? row.segments.map(function (s) {
          return '<span class="seg-tag" style="background:' + s.color + '18;color:' + s.color
            + '"><span class="dot" style="background:' + s.color + '"></span>' + esc(s.short) + '</span>';
        }).join('')
        : '<span class="co-sub" style="margin:0">all industries</span>')
      + '</div></div></div></td>'
      + '<td class="num">' + row.open_count + '<div class="co-sub">' + moneyShort(row.open_mrr) + '</div></td>'
      + '<td class="num">' + money(row.won_mrr) + '</td>'
      + '<td class="num">' + (row.win_rate === null ? '-' : row.win_rate + '%') + '</td></tr>';
  });
  html += '</tbody></table></div>';

  // Channels
  html += '<div class="panel"><h3>Where deals come from</h3><table class="list"><thead><tr>'
    + '<th>Source</th><th class="num">Deals</th><th class="num">Engaged</th><th class="num">Won MRR</th>'
    + '</tr></thead><tbody>';
  data.channels.forEach(function (row) {
    html += '<tr style="cursor:default"><td>' + esc(row.label) + '</td>'
      + '<td class="num">' + row.count + '</td>'
      + '<td class="num">' + row.engage_rate + '%</td>'
      + '<td class="num">' + money(row.won_mrr) + '</td></tr>';
  });
  html += '</tbody></table></div>';

  // Why we lose
  html += '<div class="panel"><h3>Why we lose</h3>';
  if (!data.lost.length) html += '<div class="co-sub">Nothing lost yet.</div>';
  data.lost.forEach(function (row) {
    html += '<div style="margin-bottom:13px"><div style="display:flex;justify-content:space-between">'
      + '<strong>' + esc(row.label) + '</strong><span>' + row.count + ' &middot; ' + money(row.mrr) + '</span></div>';
    row.notes.forEach(function (note) {
      html += '<div class="co-sub" style="margin-top:4px">' + esc(note.company) + ': ' + esc(note.note) + '</div>';
    });
    html += '</div>';
  });
  html += '</div>';

  // New MRR trend
  html += '<div class="panel wide"><h3>New MRR won, last 12 months</h3><div class="bars">';
  var peak = Math.max.apply(null, data.months.map(function (m) { return m.mrr; }).concat([1]));
  data.months.forEach(function (month) {
    var height = Math.round(100 * month.mrr / peak);
    html += '<div class="b" style="height:' + Math.max(height, 1) + '%" title="' + esc(month.label) + ' '
      + money(month.mrr) + '"><span>' + esc(month.label) + '</span></div>';
  });
  html += '</div><div style="height:22px"></div></div>';

  return html + '</div></div>';
}

/* ----------------------------------------------------------------- DRAWER */

function openDeal(id, keepTab) {
  // The cold mail travels with the deal, so the drawer never has to go and
  // fetch it when somebody opens the Mail tab. keepTab is for the actions on
  // that tab: they reopen the deal and must not throw you back to Overview.
  Promise.all([
    api('/api/deals/' + id),
    api('/api/mail/' + id)
  ]).then(function (both) {
    var data = both[0];
    data.mail = both[1];
    state.drawer = { kind: 'deal', data: data };
    if (!keepTab) state.drawerTab = 'overview';
    paintDrawer();
  }).catch(function (error) { toast(error.message); });
}

function openClient(id) {
  api('/api/clients/' + id).then(function (data) {
    state.drawer = { kind: 'client', data: data };
    state.drawerTab = 'overview';
    paintDrawer();
  }).catch(function (error) { toast(error.message); });
}

function openCompany(id) {
  api('/api/companies/' + id).then(function (data) {
    if (data.deals.length) { openDeal(data.deals[0].id); return; }
    state.drawer = { kind: 'company', data: data };
    state.drawerTab = 'overview';
    paintDrawer();
  }).catch(function (error) { toast(error.message); });
}

function closeDrawer() {
  state.drawer = null;
  document.getElementById('drawer').classList.remove('on');
  document.getElementById('scrim').classList.remove('on');
}

function paintDrawer() {
  var drawer = document.getElementById('drawer');
  if (!state.drawer) { closeDrawer(); return; }
  drawer.innerHTML = state.drawer.kind === 'deal' ? dealDrawer(state.drawer.data)
    : state.drawer.kind === 'client' ? clientDrawer(state.drawer.data)
      : companyDrawer(state.drawer.data);
  drawer.classList.add('on');
  document.getElementById('scrim').classList.add('on');
}

function dealDrawer(payload) {
  var deal = payload.deal;
  var mail = payload.mail || { status: 'none' };
  var mailLabel = { none: 'Mail \u00b7 to write', draft: 'Mail \u00b7 drafted',
    sent: 'Mail \u00b7 sent', skipped: 'Mail \u00b7 skipped' }[mail.status] || 'Mail';
  var tabs = [['overview', 'Overview'], ['mail', mailLabel],
    ['activity', 'Activity (' + payload.notes.length + ')'],
    ['contacts', 'Contacts (' + payload.contacts.length + ')'], ['quotes', 'Quotes (' + payload.quotes.length + ')']];

  var html = '<header><div class="top">'
    + '<div class="seg-bar" style="background:' + deal.segment_color + ';min-height:46px"></div>'
    + '<div style="flex:1"><h2>' + esc(deal.company) + '</h2>'
    + '<div class="sub">' + segTag(deal) + '<span>' + esc(deal.flag) + ' ' + esc(deal.city || '') + '</span>'
    + '<span>&middot;</span><span>' + esc(deal.title) + '</span></div></div>'
    + '<button class="btn ghost sm" data-act="close-drawer">Close</button></div>'
    + '<div class="sub" style="margin:12px 0 0;align-items:center">'
    + '<select data-act="stage" style="padding:6px 10px;border:1px solid var(--line);border-radius:8px">'
    + option(state.meta.stages.concat(state.meta.extra_stages), deal.stage) + '</select>'
    + '<span>owned by</span>' + avatar(deal.owner) + '<span>' + esc(deal.owner ? deal.owner.name : '') + '</span>'
    + '<span class="count-pill">' + deal.days_in_stage + 'd in stage</span>'
    + (deal.trial_day !== null && deal.trial_day !== undefined
      ? '<span class="count-pill">trial day ' + deal.trial_day + ' of ' + state.meta.app.trial_days + '</span>' : '')
    + '</div>'
    + '<div class="tabs">' + tabs.map(function (tab) {
      return '<button data-tab="' + tab[0] + '" class="' + (state.drawerTab === tab[0] ? 'on' : '') + '">'
        + tab[1] + '</button>';
    }).join('') + '</div></header><div class="content">';

  if (state.drawerTab === 'overview') {
    html += '<div class="money-box"><div class="lbl">Monthly recurring</div>'
      + '<div class="big">' + money(deal.mrr) + '</div>';
    deal.seat_lines.forEach(function (line) {
      html += '<div class="seat-row"><div><strong>' + line.seats + '</strong> &times; ' + esc(line.label)
        + '<div class="who">' + (line.rate_missing ? 'price still to agree'
          : money(line.rate) + ' per user / month') + '</div></div>'
        + '<div><strong>' + (line.rate_missing ? '-' : money(line.mrr)) + '</strong></div></div>';
    });
    if (deal.rate_missing) {
      // Without this the only chance to price a negotiated tier is at creation,
      // which is the one moment nobody has negotiated anything yet.
      html += '<div class="seat-warn">Those seats are not in the monthly figure yet. '
        + 'Set what was agreed and the forecast stops reading low.'
        + deal.seat_lines.filter(function (line) { return line.rate_missing; })
          .map(function (line) {
            return '<div class="seat-warn-row"><label>' + esc(line.label) + ' per user / month</label>'
              + '<input id="d-rate-' + line.key + '" type="number" min="0" step="1" placeholder="0">'
              + '<button class="btn sm primary" data-act="save-rate" data-tier="' + line.key
              + '" data-id="' + deal.id + '">Save</button></div>';
          }).join('')
        + '</div>';
    }
    if (deal.onboarding_fee) {
      html += '<div class="seat-row"><div>Onboarding<div class="who">one-off</div></div>'
        + '<div><strong>' + money(deal.onboarding_fee) + '</strong></div></div>';
    }
    html += '<div class="seat-row" style="border-top-width:2px"><div><strong>Over '
      + deal.contract_months + ' months</strong></div><div><strong>' + money(deal.acv)
      + '</strong></div></div></div>';

    html += '<dl class="kv">'
      + '<dt>Industry</dt><dd>' + segTag(deal) + ' ' + esc(deal.segment_label) + '</dd>'
      + '<dt>Plan</dt><dd>' + esc(deal.plan_label) + '</dd>'
      + '<dt>Users</dt><dd>' + deal.seats + ' of ' + (deal.field_staff || '?') + ' field staff</dd>'
      + '<dt>Probability</dt><dd>' + deal.probability + '%, weighted ' + money(deal.weighted) + '</dd>'
      + '<dt>Source</dt><dd>' + esc(deal.channel_label) + '</dd>'
      + '<dt>Touches</dt><dd>' + deal.touch_count
      + (deal.days_since_touch !== null ? ', last ' + deal.days_since_touch + ' days ago' : '') + '</dd>'
      + '<dt>Expected close</dt><dd>' + esc(deal.expected_close_date || 'not set') + '</dd>'
      + '</dl>';

    html += '<div style="margin-top:18px" class="field"><label>Next step</label>'
      + '<div style="display:flex;gap:8px">'
      + '<input id="d-step" value="' + esc(deal.next_action || '') + '" placeholder="What happens next">'
      + '<input id="d-step-date" type="date" value="' + esc(deal.next_action_date || '') + '" style="max-width:160px">'
      + '<button class="btn sm primary" data-act="save-step">Save</button></div></div>';

    if (deal.lost_reason) {
      html += '<div class="field"><label>Lost because</label><div>' + esc(deal.lost_reason_label)
        + (deal.lost_reason_note ? ' - ' + esc(deal.lost_reason_note) : '') + '</div></div>';
    }
    if (deal.notes) {
      html += '<div class="field"><label>Account note</label><div style="line-height:1.65">'
        + esc(deal.notes) + '</div></div>';
    }

    html += '<h3 style="font-size:13px;margin:22px 0 10px">Stage history</h3><div class="timeline">';
    payload.history.slice().reverse().forEach(function (step) {
      html += '<div class="step"><strong>' + esc(step.to_label) + '</strong>'
        + (step.from_label ? ' <span style="color:var(--muted)">from ' + esc(step.from_label) + '</span>' : '')
        + '<div class="co-sub">' + step.at.slice(0, 10) + '</div></div>';
    });
    html += '</div>';
  }

  if (state.drawerTab === 'mail') {
    html += '<div class="mail-editor in-drawer">' + mailEditor(mail) + '</div>';
  }

  if (state.drawerTab === 'activity') {
    html += '<div class="field"><label>Log something</label>'
      + '<select id="n-kind" style="margin-bottom:8px">' + option(state.meta.note_kinds, 'call') + '</select>'
      + '<textarea id="n-body" placeholder="What happened"></textarea>'
      + '<button class="btn primary sm" data-act="add-note" style="margin-top:8px">Add to the log</button></div>';
    payload.notes.forEach(function (note) {
      html += '<div class="note ' + esc(note.kind) + '"><div class="h">'
        + '<span class="kind-tag">' + esc(note.kind_label) + '</span>'
        + '<span>' + note.created_at.slice(0, 10) + '</span>'
        + '<span>' + esc(note.author ? note.author.name : '') + '</span></div>'
        + '<div class="b">' + esc(note.body) + '</div></div>';
    });
    if (!payload.notes.length) html += '<div class="empty">Nothing logged yet.</div>';
  }

  if (state.drawerTab === 'contacts') {
    payload.contacts.forEach(function (contact) {
      html += '<div class="card" style="padding:13px;margin-bottom:9px">'
        + '<div style="font-weight:650">' + esc(contact.name)
        + (contact.is_primary ? ' <span class="count-pill">primary</span>' : '') + '</div>'
        + '<div class="co-sub">' + esc(contact.role_title || '') + '</div>'
        + '<div class="co-sub">' + (contact.email ? '<a href="mailto:' + esc(contact.email) + '">'
          + esc(contact.email) + '</a>' : '') + (contact.phone ? ' &middot; ' + esc(contact.phone) : '') + '</div>'
        + '</div>';
    });
    if (!payload.contacts.length) html += '<div class="empty">No contacts yet.</div>';
  }

  if (state.drawerTab === 'quotes') {
    html += '<button class="btn primary sm" data-act="new-quote" style="margin-bottom:14px">'
      + 'Freeze a quote from this deal</button>';
    html += '<div class="co-sub" style="margin-bottom:14px">A quote copies the seats, rates and term as '
      + 'they are now. Editing the deal afterwards never changes a document the customer already has.</div>';
    payload.quotes.forEach(function (quote) {
      html += '<div class="card" style="padding:13px;margin-bottom:9px;display:flex;'
        + 'justify-content:space-between;align-items:center">'
        + '<div><div style="font-weight:700">' + esc(quote.number)
        + ' <span class="stage-tag' + (quote.status === 'accepted' ? ' won' : '') + '">'
        + esc(quote.status) + '</span></div>'
        + '<div class="co-sub">' + money(quote.mrr) + ' / mo &middot; ' + quote.seats + ' users &middot; '
        + quote.contract_months + ' months &middot; ' + money(quote.acv) + ' total</div></div>'
        + '<a class="btn sm" href="' + esc(quote.url) + '" target="_blank">Open</a></div>';
    });
    if (!payload.quotes.length) html += '<div class="empty">No quotes on this deal yet.</div>';
  }

  return html + '</div>';
}

function clientDrawer(payload) {
  var client = payload.client;
  var html = '<header><div class="top">'
    + '<div class="seg-bar" style="background:' + client.segment_color + ';min-height:46px"></div>'
    + '<div style="flex:1"><h2>' + esc(client.company) + '</h2>'
    + '<div class="sub">' + segTag(client) + '<span>' + esc(client.flag) + ' ' + esc(client.city || '') + '</span>'
    + '<span class="health" style="background:' + client.health_color + '"></span>'
    + '<span>' + esc(client.health_label) + '</span></div></div>'
    + '<button class="btn ghost sm" data-act="close-drawer">Close</button></div>'
    + '<div class="tabs"><button class="on">Post-sale</button></div></header><div class="content">';

  html += '<div class="money-box"><div class="lbl">Live monthly recurring</div>'
    + '<div class="big">' + money(client.mrr) + '</div>'
    + '<div class="seat-row"><div>' + client.seats + ' users live</div>'
    + '<div>' + money(client.arr) + ' a year</div></div></div>';

  html += '<dl class="kv">'
    + '<dt>Industry</dt><dd>' + segTag(client) + ' ' + esc(client.segment_label) + '</dd>'
    + '<dt>Live since</dt><dd>' + esc(client.started_on || '-') + ' (' + client.months_live + ' months)</dd>'
    + '<dt>Go live</dt><dd>' + esc(client.go_live_on || '-') + '</dd>'
    + '<dt>Next check-in</dt><dd>' + (client.next_meeting_date
      ? esc(client.next_meeting_date) + ' ' + dueTag(client.next_meeting_date) : 'none') + '</dd>'
    + '<dt>Owner</dt><dd>' + esc(client.owner ? client.owner.name : '') + '</dd>'
    + '<dt>Status</dt><dd>' + esc(client.status)
    + (client.churned_on ? ' on ' + esc(client.churned_on) : '') + '</dd>'
    + '</dl>';

  if (client.churn_reason) {
    html += '<div class="field" style="margin-top:14px"><label>Churn reason</label><div>'
      + esc(client.churn_reason) + '</div></div>';
  }
  if (client.notes) {
    html += '<div class="field"><label>Account note</label><div style="line-height:1.65">'
      + esc(client.notes) + '</div></div>';
  }

  if (client.status === 'active') {
    html += '<div class="field" style="margin-top:18px"><label>Health</label>'
      + '<select data-act="health">' + option(state.meta.health_states, client.health) + '</select></div>'
      + '<button class="btn primary sm" data-act="log-meeting">Log a check-in</button>';
  }

  html += '<h3 style="font-size:13px;margin:24px 0 10px">Check-in history</h3>';
  payload.meetings.forEach(function (meeting) {
    html += '<div class="note"><div class="h"><span class="kind-tag">' + esc(meeting.held_on) + '</span>'
      + '<span>' + esc(meeting.health_label) + '</span>'
      + '<span>' + esc(meeting.author ? meeting.author.name : '') + '</span></div>'
      + '<div class="b">' + esc(meeting.summary || '') + '</div>'
      + (meeting.actions ? '<div class="co-sub" style="margin-top:5px"><strong>Actions:</strong> '
        + esc(meeting.actions) + '</div>' : '') + '</div>';
  });
  if (!payload.meetings.length) html += '<div class="empty">No check-ins logged yet.</div>';

  return html + '</div>';
}

function companyDrawer(payload) {
  var company = payload.company;
  return '<header><div class="top">'
    + '<div class="seg-bar" style="background:' + company.segment_color + ';min-height:46px"></div>'
    + '<div style="flex:1"><h2>' + esc(company.name) + '</h2>'
    + '<div class="sub">' + segTag(company) + '<span>' + esc(company.flag) + ' '
    + esc(company.city || '') + '</span></div></div>'
    + '<button class="btn ghost sm" data-act="close-drawer">Close</button></div></header>'
    + '<div class="content"><dl class="kv">'
    + '<dt>Industry</dt><dd>' + esc(company.segment_label) + '</dd>'
    + '<dt>Field staff</dt><dd>' + (company.field_staff || '-') + '</dd>'
    + '<dt>Sites</dt><dd>' + (company.sites || '-') + '</dd>'
    + '<dt>Runs today</dt><dd>' + esc(company.current_tool || '-') + '</dd>'
    + '<dt>Owner</dt><dd>' + esc(company.owner ? company.owner.name : '') + '</dd>'
    + '</dl><div style="margin-top:16px;line-height:1.65">' + esc(company.notes || '') + '</div>'
    + '<button class="btn primary sm" data-act="new-deal-for" data-company="' + company.id
    + '" style="margin-top:18px">Open a deal on this company</button></div>';
}

/* ------------------------------------------------------------------ MODAL */

function modal(html) {
  document.getElementById('modal').innerHTML = html;
  document.getElementById('modal-wrap').classList.add('on');
}
function closeModal() { document.getElementById('modal-wrap').classList.remove('on'); }

function newDealModal(companyId) {
  modal('<h3>New deal</h3>'
    + '<div class="hint">Leave the owner alone and the deal goes to whoever owns that industry.</div>'
    + '<div class="body">'
    + '<div class="field"><label>Company</label><input id="m-company" placeholder="Organisation name"></div>'
    + '<div class="grid2">'
    + '<div class="field"><label>Industry</label><select id="m-segment">'
    + option(state.meta.segments, state.segments[0] || 'cleaning') + '</select></div>'
    + '<div class="field"><label>Country</label><select id="m-country">'
    + option(state.meta.countries, 'BE') + '</select></div></div>'
    + '<div class="field"><label>City</label><input id="m-city"></div>'
    + '<div class="grid4">'
    + state.meta.seat_tiers.map(function (tier) {
      return '<div class="field"><label>' + esc(tier.label) + '</label>'
        + '<input id="m-' + tier.key + '" type="number" min="0" value="0">'
        + '<div class="co-sub">' + (tier.custom ? 'Custom price' : money(tier.rate) + ' / user')
        + '</div></div>';
    }).join('') + '</div>'
    + customRateField()
    + '<div class="grid2">'
    + '<div class="field"><label>Term (months)</label><input id="m-months" type="number" value="12"></div>'
    + '<div class="field"><label>Source</label><select id="m-channel">'
    + option(state.meta.channels, 'outbound_mail') + '</select></div></div>'
    + '</div><div class="foot"><button class="btn" data-act="close-modal">Cancel</button>'
    + '<button class="btn primary" data-act="save-deal" data-company="' + (companyId || '') + '">Create</button></div>');
}

function customRateField() {
  // Enterprise is "Custom" on Sabertask's price list, so the rep types what was
  // negotiated. Left empty it stays 0, and the deal says its MRR reads short.
  var custom = (state.meta.seat_tiers || []).filter(function (tier) { return tier.custom; });
  if (!custom.length) return '';
  return custom.map(function (tier) {
    return '<div class="field"><label>' + esc(tier.label) + ' rate per user / month</label>'
      + '<input id="m-rate-' + tier.key + '" type="number" min="0" step="1" placeholder="Negotiated">'
      + '<div class="co-sub">Only needed if you sold ' + esc(tier.label) + ' seats</div></div>';
  }).join('');
}

function completeModal(itemId, title) {
  modal('<h3>Done: ' + esc(title) + '</h3>'
    + '<div class="hint">What happens next on this deal? A deal with no next step is a deal going quiet, '
    + 'so say so deliberately if there really is nothing.</div>'
    + '<div class="body">'
    + '<div class="field"><label>What did you do</label><textarea id="c-note" '
    + 'placeholder="Optional, goes into the activity log"></textarea></div>'
    + '<div class="field"><label>Next step</label><input id="c-step" placeholder="The next thing"></div>'
    + '<div class="field"><label>By when</label><input id="c-date" type="date"></div>'
    + '</div><div class="foot">'
    + '<button class="btn" data-act="complete-nothing" data-id="' + esc(itemId) + '">Nothing planned</button>'
    + '<button class="btn primary" data-act="complete-next" data-id="' + esc(itemId) + '">Save</button></div>');
}

function lostModal(dealId) {
  modal('<h3>Why did we lose it?</h3>'
    + '<div class="hint">The reason is the only thing a lost deal is still worth.</div>'
    + '<div class="body">'
    + '<div class="field"><label>Reason</label><select id="l-reason">'
    + option(state.meta.lost_reasons, 'price') + '</select></div>'
    + '<div class="field"><label>What actually happened</label><textarea id="l-note"></textarea></div>'
    + '</div><div class="foot"><button class="btn" data-act="close-modal">Cancel</button>'
    + '<button class="btn primary" data-act="save-lost" data-id="' + dealId + '">Mark lost</button></div>');
}

function meetingModal(clientId) {
  modal('<h3>Log a check-in</h3>'
    + '<div class="hint">The next check-in moves one month on from the date you held this one.</div>'
    + '<div class="body">'
    + '<div class="field"><label>Held on</label><input id="mt-date" type="date" value="'
    + new Date().toISOString().slice(0, 10) + '"></div>'
    + '<div class="field"><label>Health</label><select id="mt-health">'
    + option(state.meta.health_states, 'green') + '</select></div>'
    + '<div class="field"><label>Summary</label><textarea id="mt-summary"></textarea></div>'
    + '<div class="field"><label>Actions</label><textarea id="mt-actions"></textarea></div>'
    + '</div><div class="foot"><button class="btn" data-act="close-modal">Cancel</button>'
    + '<button class="btn primary" data-act="save-meeting" data-id="' + clientId + '">Log it</button></div>');
}

function taskModal() {
  modal('<h3>New task</h3><div class="body">'
    + '<div class="field"><label>What</label><input id="t-title"></div>'
    + '<div class="grid2">'
    + '<div class="field"><label>Kind</label><select id="t-kind">' + option(state.meta.task_kinds, 'todo') + '</select></div>'
    + '<div class="field"><label>Priority</label><select id="t-priority">'
    + option(state.meta.priorities, 'normal') + '</select></div></div>'
    + '<div class="field"><label>Due</label><input id="t-due" type="date" value="'
    + new Date().toISOString().slice(0, 10) + '"></div>'
    + '</div><div class="foot"><button class="btn" data-act="close-modal">Cancel</button>'
    + '<button class="btn primary" data-act="save-task">Create</button></div>');
}

function importModal() {
  modal('<h3>Import prospects from CSV</h3>'
    + '<div class="hint">Columns are guessed from the header row. Every row becomes a company, a primary '
    + 'contact and a lead, routed to the rep who owns that industry. A prospecting export works as it '
    + 'comes: the city and the country are read out of a one-line address, and a SIC code picks the '
    + 'industry over the one below.</div>'
    + '<div class="body"><div class="field"><label>File</label>'
    + '<input id="i-file" type="file" accept=".csv,text/csv"></div>'
    + '<div class="field"><label>Industry if the file does not say</label>'
    + '<select id="i-segment">' + option(state.meta.segments, 'cleaning') + '</select></div>'
    + '<div id="i-preview"></div></div>'
    + '<div class="foot"><button class="btn" data-act="close-modal">Cancel</button>'
    + '<button class="btn primary" data-act="do-import">Analyse and import</button></div>');
}

/* ------------------------------------------------------------------- data */

function load() {
  var jobs = [];
  if (state.nav === 'today') {
    jobs.push(api('/api/today' + qs('scope=' + state.scope)).then(function (data) {
      state.data.today = data;
    }));
  }
  if (state.nav === 'pipeline') {
    var extra = [];
    if (state.owner) extra.push('owner_id=' + state.owner);
    if (state.channel) extra.push('channel=' + state.channel);
    jobs.push(api('/api/deals' + qs(extra.join('&'))).then(function (data) {
      state.data.deals = data;
    }));
  }
  if (state.nav === 'companies') {
    jobs.push(api('/api/companies' + qs(state.owner ? 'owner_id=' + state.owner : '')).then(function (data) {
      state.data.companies = data;
    }));
  }
  if (state.nav === 'leads') {
    jobs.push(api('/api/leads' + qs('status=' + state.leadStatus
      + (state.leadSearchId ? '&search_id=' + state.leadSearchId : ''))).then(function (data) {
      state.data.leads = data;
    }));
    jobs.push(api('/api/leads/searches').then(function (data) {
      state.data.leadSearches = data;
    }));
  }
  if (state.nav === 'clients') {
    jobs.push(api('/api/clients' + qs('status=' + state.clientStatus)).then(function (data) {
      state.data.clients = data;
    }));
  }
  if (state.nav === 'settings') {
    jobs.push(api('/api/settings').then(function (data) { state.data.settings = data; }));
  }
  if (state.nav === 'reports') {
    jobs.push(api('/api/reports').then(function (data) { state.data.reports = data; }));
  }
  // Today's badge should be right whichever view is open.
  if (state.nav !== 'today') {
    jobs.push(api('/api/today?scope=mine').then(function (data) { state.data.today = data; }));
  }
  return Promise.all(jobs).then(paint).catch(function (error) {
    if (error.message !== 'auth') toast(error.message);
  });
}

function paint() {
  var views = {
    today: viewToday, pipeline: viewPipeline, companies: viewCompanies,
    leads: viewLeads, clients: viewClients, reports: viewReports,
    settings: viewSettings
  };
  document.getElementById('view-name').textContent =
    (NAV.filter(function (n) { return n.key === state.nav; })[0] || {}).label || '';
  document.getElementById('body').innerHTML = views[state.nav]();
  renderRail();
  renderDesk();
  if (state.nav === 'pipeline' && state.pipelineView === 'board') wireDragDrop();
}

/* Both settings live in /api/meta as well: the country list drives filters
   everywhere and the currency drives every amount on screen, so a change to
   either is pulled back before anything is drawn again. */
function refreshMeta() {
  return api('/api/meta').then(function (meta) {
    state.meta = meta;
    return load();
  });
}

function go(nav) {
  state.nav = nav;
  document.getElementById('body').innerHTML = '<div class="view"><div class="empty">Loading</div></div>';
  load();
}

/* -------------------------------------------------------------- drag drop */

function wireDragDrop() {
  var dragged = null;
  document.querySelectorAll('.deal-card').forEach(function (card) {
    card.addEventListener('dragstart', function () {
      dragged = card.dataset.deal;
      card.classList.add('dragging');
    });
    card.addEventListener('dragend', function () { card.classList.remove('dragging'); });
  });
  document.querySelectorAll('.col').forEach(function (col) {
    col.addEventListener('dragover', function (event) {
      event.preventDefault();
      col.classList.add('drop');
    });
    col.addEventListener('dragleave', function () { col.classList.remove('drop'); });
    col.addEventListener('drop', function (event) {
      event.preventDefault();
      col.classList.remove('drop');
      if (!dragged) return;
      moveStage(dragged, col.dataset.stage);
      dragged = null;
    });
  });
}

function moveStage(dealId, stage) {
  if (stage === 'lost') { lostModal(dealId); return; }
  api('/api/deals/' + dealId, { method: 'PATCH', body: { stage: stage } })
    .then(function () {
      toast('Moved to ' + (state.meta.stages.concat(state.meta.extra_stages)
        .filter(function (s) { return s.key === stage; })[0] || {}).label);
      if (state.drawer && state.drawer.kind === 'deal') openDeal(dealId);
      load();
    })
    .catch(function (error) { toast(error.message); });
}

/* --------------------------------------------------------------- handlers */

document.addEventListener('click', function (event) {
  var target = event.target.closest('[data-nav],[data-act],[data-seg],[data-view],[data-tab],'
    + '[data-deal],[data-company],[data-client],[data-complete],[data-open-deal],'
    + '[data-search]');
  if (!target) return;

  if (target.dataset.nav) { go(target.dataset.nav); return; }

  if (target.dataset.seg !== undefined && !target.dataset.act) {
    var key = target.dataset.seg;
    if (!key) state.segments = [];
    else {
      var at = state.segments.indexOf(key);
      if (at >= 0) state.segments.splice(at, 1); else state.segments.push(key);
    }
    load();
    return;
  }

  if (target.dataset.search && !target.dataset.act) {
    var picked = parseInt(target.dataset.search, 10);
    state.leadSearchId = state.leadSearchId === picked ? null : picked;
    load();
    return;
  }


  if (target.dataset.view) { state.pipelineView = target.dataset.view; paint(); return; }
  if (target.dataset.tab) { state.drawerTab = target.dataset.tab; paintDrawer(); return; }

  if (target.dataset.complete) {
    event.stopPropagation();
    var item = target.closest('.feed-item');
    var title = item ? item.querySelector('.t').textContent : 'this';
    if (target.dataset.complete.indexOf('deal-') === 0) {
      completeModal(target.dataset.complete, title);
    } else {
      api('/api/today/' + target.dataset.complete + '/complete', { method: 'POST', body: {} })
        .then(function () { toast('Done'); load(); })
        .catch(function (error) { toast(error.message); });
    }
    return;
  }

  if (target.dataset.openDeal) { openDeal(target.dataset.openDeal); return; }
  if (target.dataset.openClient && !target.dataset.openDeal) { openClient(target.dataset.openClient); return; }

  if (target.dataset.deal && !target.dataset.act) { openDeal(target.dataset.deal); return; }
  if (target.dataset.client && !target.dataset.act) { openClient(target.dataset.client); return; }
  if (target.dataset.company && !target.dataset.act) { openCompany(target.dataset.company); return; }

  var act = target.dataset.act;
  if (!act) return;

  if (act === 'logout') {
    api('/api/logout', { method: 'POST' }).then(function () { window.location.href = '/login'; });
  }
  if (act === 'close-drawer') closeDrawer();
  if (act === 'close-modal') closeModal();
  if (act === 'new-task') taskModal();
  if (act === 'new-company' || act === 'new-deal') newDealModal();
  if (act === 'new-deal-for') newDealModal(target.dataset.company);
  if (act === 'log-meeting') meetingModal(state.drawer.data.client.id);
  if (act === 'import') importModal();

  if (act === 'save-step') {
    api('/api/deals/' + state.drawer.data.deal.id, {
      method: 'PATCH',
      body: {
        next_action: document.getElementById('d-step').value || null,
        next_action_date: document.getElementById('d-step-date').value || null
      }
    }).then(function () {
      toast('Next step saved');
      openDeal(state.drawer.data.deal.id);
      load();
    }).catch(function (error) { toast(error.message); });
  }

  if (act === 'add-note') {
    var body = document.getElementById('n-body').value.trim();
    if (!body) { toast('Write something first'); return; }
    api('/api/deals/' + state.drawer.data.deal.id + '/notes', {
      method: 'POST',
      body: { kind: document.getElementById('n-kind').value, body: body }
    }).then(function () {
      toast('Logged');
      openDeal(state.drawer.data.deal.id);
      load();
    }).catch(function (error) { toast(error.message); });
  }

  if (act === 'country-add') {
    var code = document.getElementById('c-code').value.trim();
    var label = document.getElementById('c-name').value.trim();
    if (code.length !== 2) { toast('A country code is two letters'); return; }
    api('/api/settings/countries', { method: 'POST', body: { code: code, label: label || code } })
      .then(function (row) {
        toast(row.flag + ' ' + row.label + ' added, searchable now');
        return refreshMeta();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'country-remove') {
    api('/api/settings/countries/' + target.dataset.code, { method: 'DELETE' })
      .then(function () { toast('Removed from the search'); return refreshMeta(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'currency') {
    api('/api/settings/currency', { method: 'PATCH', body: { currency: target.dataset.code } })
      .then(function (block) {
        toast('Reading in ' + block.current);
        return refreshMeta();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'lead-search') {
    var brief = document.getElementById('lead-brief').value.trim();
    if (brief.length < 4) { toast('Say what you are looking for'); return; }
    state.leadBrief = brief;
    state.leadSearching = true;
    state.leadStatus = 'new';
    paint();
    api('/api/leads/search', { method: 'POST', body: { brief: brief } })
      .then(function (result) {
        state.leadSearching = false;
        state.leadResult = result;
        state.leadSearchId = result.search_id;
        toast(result.shown + ' on the list');
        load();
      }).catch(function (error) {
        state.leadSearching = false;
        state.leadResult = null;
        toast(error.message);
        paint();
      });
  }

  if (act === 'lead-all-searches') {
    state.leadSearchId = null;
    load();
  }

  if (act === 'lead-add-all') {
    api('/api/leads/add-all', {
      method: 'POST',
      body: { segment: state.segments.join(','), search_id: state.leadSearchId }
    }).then(function (result) {
      var desks = Object.keys(result.owners).map(function (name) {
        return result.owners[name] + ' to ' + name;
      }).join(', ');
      toast(result.added + ' added' + (desks ? ': ' + desks : ''));
      load();
    }).catch(function (error) { toast(error.message); });
  }

  if (act === 'lead-add') {
    api('/api/leads/' + target.dataset.id + '/add', { method: 'POST', body: {} })
      .then(function (result) {
        toast('Added, routed to ' + (result.owner || 'you'));
        load();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'lead-dismiss') {
    api('/api/leads/' + target.dataset.id + '/dismiss', { method: 'POST', body: {} })
      .then(function () { toast('Left alone'); load(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'mail-draft-all') {
    toast('Writing the open ones');
    api('/api/mail/draft-all?scope=team', { method: 'POST', body: {} })
      .then(function (result) {
        toast(result.written ? result.written + ' drafted' : 'Nothing left to draft');
        load();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'mail-draft') {
    api('/api/mail/' + mailDeal() + '/draft', { method: 'POST', body: {} })
      .then(function () { toast('Drafted'); afterMail(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'mail-save') {
    api('/api/mail/' + mailDeal(), {
      method: 'PATCH',
      body: {
        subject: document.getElementById('mail-subject').value,
        body: document.getElementById('mail-body').value
      }
    }).then(function () { toast('Saved'); afterMail(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'mail-copy') {
    var text = 'Subject: ' + document.getElementById('mail-subject').value + '\n\n'
      + document.getElementById('mail-body').value;
    // Clipboard access can be refused; the mail is on screen either way, so a
    // failure says so rather than pretending it worked.
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text)
        .then(function () { toast('Copied, paste it in your mailbox'); })
        .catch(function () { toast('Could not copy, select the text instead'); });
    } else {
      toast('Could not copy, select the text instead');
    }
  }

  if (act === 'mail-sent') {
    api('/api/mail/' + mailDeal() + '/sent', { method: 'POST', body: {} })
      .then(function (row) {
        toast('Logged as sent' + (row.stage === 'contacted' ? ', moved to contacted' : ''));
        afterMail();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'mail-skip') {
    api('/api/mail/' + mailDeal() + '/skip', { method: 'POST', body: { reason: null } })
      .then(function () { toast('Left alone'); afterMail(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'new-quote') {
    api('/api/deals/' + state.drawer.data.deal.id + '/quotes', { method: 'POST', body: {} })
      .then(function (quote) {
        toast('Quote ' + quote.number + ' frozen');
        openDeal(state.drawer.data.deal.id);
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'save-deal') {
    var seats = {};
    state.meta.seat_tiers.forEach(function (tier) {
      seats[tier.key + '_seats'] = parseInt(document.getElementById('m-' + tier.key).value, 10) || 0;
      var rateBox = document.getElementById('m-rate-' + tier.key);
      if (rateBox) seats[tier.key + '_rate'] = parseFloat(rateBox.value) || 0;
    });
    api('/api/deals', {
      method: 'POST',
      body: Object.assign({
        company_id: target.dataset.company ? parseInt(target.dataset.company, 10) : null,
        company_name: document.getElementById('m-company').value,
        segment: document.getElementById('m-segment').value,
        country: document.getElementById('m-country').value,
        city: document.getElementById('m-city').value,
        contract_months: parseInt(document.getElementById('m-months').value, 10) || 12,
        channel: document.getElementById('m-channel').value
      }, seats)
    }).then(function (deal) {
      closeModal();
      toast('Deal created, routed to ' + (deal.owner ? deal.owner.name : 'you'));
      load();
    }).catch(function (error) { toast(error.message); });
  }

  if (act === 'save-rate') {
    var tier = target.dataset.tier;
    var body = {};
    body[tier + '_rate'] = parseFloat(document.getElementById('d-rate-' + tier).value) || 0;
    api('/api/deals/' + target.dataset.id, { method: 'PATCH', body: body })
      .then(function () {
        toast('Rate saved');
        openDeal(parseInt(target.dataset.id, 10));
        load();
      }).catch(function (error) { toast(error.message); });
  }

  if (act === 'save-lost') {
    api('/api/deals/' + target.dataset.id, {
      method: 'PATCH',
      body: {
        stage: 'lost',
        lost_reason: document.getElementById('l-reason').value,
        lost_reason_note: document.getElementById('l-note').value || null
      }
    }).then(function () { closeModal(); toast('Marked lost'); load(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'complete-next' || act === 'complete-nothing') {
    var nothing = act === 'complete-nothing';
    api('/api/today/' + target.dataset.id + '/complete', {
      method: 'POST',
      body: {
        log_note: document.getElementById('c-note').value || null,
        next_step: nothing ? null : (document.getElementById('c-step').value || null),
        next_step_date: nothing ? null : (document.getElementById('c-date').value || null),
        nothing_planned: nothing
      }
    }).then(function () { closeModal(); toast('Done'); load(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'save-task') {
    api('/api/tasks', {
      method: 'POST',
      body: {
        title: document.getElementById('t-title').value,
        kind: document.getElementById('t-kind').value,
        priority: document.getElementById('t-priority').value,
        due_date: document.getElementById('t-due').value || null
      }
    }).then(function () { closeModal(); toast('Task added'); load(); })
      .catch(function (error) { toast(error.message); });
  }

  if (act === 'save-meeting') {
    api('/api/clients/' + target.dataset.id + '/meetings', {
      method: 'POST',
      body: {
        held_on: document.getElementById('mt-date').value || null,
        health: document.getElementById('mt-health').value,
        summary: document.getElementById('mt-summary').value || null,
        actions: document.getElementById('mt-actions').value || null
      }
    }).then(function () {
      closeModal();
      toast('Check-in logged, next one scheduled');
      openClient(target.dataset.id);
      load();
    }).catch(function (error) { toast(error.message); });
  }

  if (act === 'do-import') {
    var fileInput = document.getElementById('i-file');
    if (!fileInput.files.length) { toast('Pick a file first'); return; }
    var form = new FormData();
    form.append('file', fileInput.files[0]);
    fetch('/api/import/analyze', { method: 'POST', body: form })
      .then(function (res) { return res.json(); })
      .then(function (analysis) {
        if (analysis.detail) throw new Error(analysis.detail);
        return api('/api/import/commit', {
          method: 'POST',
          body: {
            rows: analysis.rows,
            mapping: analysis.mapping,
            default_segment: document.getElementById('i-segment').value
          }
        });
      })
      .then(function (result) {
        closeModal();
        toast(result.created + ' imported, ' + result.skipped + ' skipped');
        load();
      })
      .catch(function (error) { toast(error.message); });
  }
});

document.addEventListener('change', function (event) {
  var target = event.target;
  if (target.dataset.filter) {
    var key = target.dataset.filter;
    state[key] = target.value;
    load();
    return;
  }
  if (target.dataset.act === 'stage') {
    moveStage(state.drawer.data.deal.id, target.value);
    return;
  }
  if (target.dataset.act === 'health') {
    api('/api/clients/' + state.drawer.data.client.id, {
      method: 'PATCH', body: { health: target.value }
    }).then(function () {
      toast('Health updated');
      openClient(state.drawer.data.client.id);
      load();
    }).catch(function (error) { toast(error.message); });
  }
});

document.getElementById('scrim').addEventListener('click', closeDrawer);
document.getElementById('modal-wrap').addEventListener('click', function (event) {
  if (event.target.id === 'modal-wrap') closeModal();
});
document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape') { closeDrawer(); closeModal(); }
});

var searchTimer;
document.getElementById('q').addEventListener('input', function (event) {
  clearTimeout(searchTimer);
  var value = event.target.value;
  searchTimer = setTimeout(function () {
    state.q = value;
    if (state.nav === 'today' || state.nav === 'reports') state.nav = 'pipeline';
    load();
  }, 280);
});

document.getElementById('btn-new').addEventListener('click', function () { newDealModal(); });
document.getElementById('btn-import').addEventListener('click', function () { importModal(); });
document.getElementById('btn-export').addEventListener('click', function () {
  window.location.href = '/api/export/contacts.csv'
    + (state.segments.length ? '?segment=' + state.segments.join(',') : '');
});

/* ------------------------------------------------------------------ start */

api('/api/meta').then(function (meta) {
  state.meta = meta;
  // A manager owns no deals of their own, so "my desk" would open empty for
  // them. They start on the whole floor instead.
  if (meta.me.role === 'manager') state.scope = 'team';
  return load();
}).catch(function (error) {
  if (error.message !== 'auth') {
    document.getElementById('body').innerHTML = '<div class="view"><div class="empty">'
      + esc(error.message) + '</div></div>';
  }
});
