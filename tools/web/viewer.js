/* Contents tree and search for the Changing Hands viewer. Works from file:// —
   data files are plain scripts that call back into this file. */
(function () {
  'use strict';
  var view = document.getElementById('view');
  var tocEl = document.getElementById('toc');
  var resEl = document.getElementById('results');
  var tabToc = document.getElementById('tab-toc');
  var tabRes = document.getElementById('tab-res');

  function pageUrl(page, rec, terms) {
    var p = String(page);
    while (p.length < 5) p = '0' + p;
    var h = rec != null ? '#r' + rec : '';
    if (terms && terms.length) h += '~' + encodeURIComponent(terms.join(' '));
    return 'pages/p' + p + '.html' + h;
  }
  function open(page, rec, terms) {
    view.src = pageUrl(page, rec, terms);
    document.body.classList.remove('side-open');
  }
  function show(which) {
    tocEl.hidden = which !== 'toc';
    resEl.hidden = which !== 'res';
    tabToc.classList.toggle('on', which === 'toc');
    tabRes.classList.toggle('on', which === 'res');
  }
  tabToc.onclick = function () { show('toc'); };
  tabRes.onclick = function () { show('res'); };
  document.getElementById('menu').onclick = function () { document.body.classList.toggle('side-open'); };

  /* ---- contents tree: node = [title, record, page, children] ---- */
  var current = null;
  function branch(nodes) {
    var ul = document.createElement('ul');
    ul.className = 'tree';
    var frag = document.createDocumentFragment();
    nodes.forEach(function (n) {
      var li = document.createElement('li');
      var row = document.createElement('div');
      row.className = 'row';
      var tw = document.createElement('button');
      tw.className = 'tw' + (n[3].length ? '' : ' leaf');
      tw.textContent = '▸';
      tw.setAttribute('aria-label', 'Expand');
      var a = document.createElement('a');
      a.href = pageUrl(n[2], n[1]);
      a.textContent = n[0];
      a.title = n[0];
      a.onclick = function (e) {
        e.preventDefault();
        if (current) current.classList.remove('cur');
        current = a;
        a.classList.add('cur');
        open(n[2], n[1]);
      };
      tw.onclick = function () {
        if (li.lastChild.tagName === 'UL') {
          li.removeChild(li.lastChild);
          tw.textContent = '▸';
        } else {
          li.appendChild(branch(n[3]));
          tw.textContent = '▾';
        }
      };
      row.appendChild(tw);
      row.appendChild(a);
      li.appendChild(row);
      frag.appendChild(li);
    });
    ul.appendChild(frag);
    return ul;
  }
  tocEl.appendChild(branch(window.TOC));

  /* ---- search ---- */
  function fold(s) {
    return s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '');
  }
  function load(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }
  var shards = {}, meta = {}, known = {};
  (window.SHARDS || []).forEach(function (k) { known[k] = true; });
  window.SHARD = function (key, words) { shards[key] = words; };
  window.META = function (n, rows) { meta[n] = rows; };
  function shardKey(w) { return w.length > 1 ? w.slice(0, 2) : w + '_'; }
  function getShard(key) {
    if (shards[key]) return Promise.resolve(shards[key]);
    if (!known[key]) return Promise.resolve({});
    return load('data/search/' + key + '.js').then(function () { return shards[key] || {}; });
  }
  function decode(s) {
    var out = [], x = 0;
    s.split(',').forEach(function (d) { x += parseInt(d, 36); out.push(x); });
    return out;
  }
  function union(lists) {
    var seen = {}, out = [];
    lists.forEach(function (l) { l.forEach(function (x) { if (!seen[x]) { seen[x] = 1; out.push(x); } }); });
    return out.sort(function (a, b) { return a - b; });
  }
  function intersect(a, b) {
    var out = [], i = 0, j = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { out.push(a[i]); i++; j++; } else if (a[i] < b[j]) i++; else j++;
    }
    return out;
  }
  function lookup(term) {
    var prefix = /\*$/.test(term);
    var w = term.replace(/\*+$/, '');
    if (!w) return Promise.resolve([]);
    var keys = [shardKey(w)];
    if (prefix && w.length === 1) keys = Object.keys(known).filter(function (k) { return k[0] === w; });
    return Promise.all(keys.map(getShard)).then(function (list) {
      var lists = [];
      list.forEach(function (words) {
        if (prefix) {
          for (var k in words) if (k.indexOf(w) === 0) lists.push(decode(words[k]));
        } else if (words[w]) lists.push(decode(words[w]));
      });
      return union(lists);
    });
  }
  function getMeta(rec) {
    var n = Math.floor(rec / 2000);
    if (meta[n]) return Promise.resolve(meta[n][rec - n * 2000]);
    return load('data/meta/' + n + '.js').then(function () { return meta[n][rec - n * 2000]; });
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }
  function highlight(text, words) {
    var html = escapeHtml(text);
    words.forEach(function (w) {
      if (w.length < 2) return;
      var re = new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
      html = html.replace(re, '<mark>$1</mark>');
    });
    return html;
  }

  var hits = [], shown = 0, words = [];
  function renderMore() {
    var more = resEl.querySelector('.more');
    if (more) more.remove();
    var batch = hits.slice(shown, shown + 50);
    shown += batch.length;
    return Promise.all(batch.map(getMeta)).then(function (rows) {
      rows.forEach(function (m, i) {
        var rec = batch[i];
        var a = document.createElement('a');
        a.className = 'res';
        a.href = pageUrl(m[0], rec, words);
        a.innerHTML = '<span class="path">' + escapeHtml(m[1]) + '</span><span class="snip">' +
          highlight(m[2], words) + '</span>';
        a.onclick = function (e) { e.preventDefault(); open(m[0], rec, words); };
        resEl.appendChild(a);
      });
      if (shown < hits.length) {
        var b = document.createElement('button');
        b.className = 'more';
        b.textContent = 'Show more (' + (hits.length - shown) + ' left)';
        b.onclick = renderMore;
        resEl.appendChild(b);
      }
    });
  }
  document.getElementById('search').onsubmit = function (e) {
    e.preventDefault();
    var q = fold(document.getElementById('q').value);
    var terms = q.match(/[0-9a-z]+\*?/g) || [];
    show('res');
    document.body.classList.add('side-open');
    resEl.innerHTML = '<p class="hint">Searching&hellip;</p>';
    if (!terms.length) { resEl.innerHTML = '<p class="hint">Type one or more words to search for.</p>'; return; }
    words = terms.map(function (t) { return t.replace(/\*$/, ''); });
    Promise.all(terms.map(lookup)).then(function (lists) {
      var res = lists.reduce(function (a, b) { return intersect(a, b); });
      if (!res.length && terms.some(function (t) { return !/\*$/.test(t); })) {
        // nothing exact: try the words as prefixes
        return Promise.all(terms.map(function (t) { return lookup(t.replace(/\*?$/, '*')); })).then(function (l2) {
          return { list: l2.reduce(function (a, b) { return intersect(a, b); }), prefix: true };
        });
      }
      return { list: res, prefix: false };
    }).then(function (r) {
      hits = r.list; shown = 0;
      resEl.innerHTML = '<p class="hint">' + (hits.length ? hits.length.toLocaleString() + ' matching record' +
        (hits.length === 1 ? '' : 's') : 'No records match') +
        (r.prefix && hits.length ? ' (matching word beginnings)' : '') + '.</p>';
      return renderMore();
    }).catch(function (err) {
      resEl.innerHTML = '<p class="hint">Search failed: ' + escapeHtml(String(err)) + '</p>';
    });
  };

  /* index.html#search=words runs a search on load, so searches can be bookmarked */
  var m = /^#search=(.*)$/.exec(location.hash);
  if (m) {
    document.getElementById('q').value = decodeURIComponent(m[1].replace(/\+/g, ' '));
    document.getElementById('search').requestSubmit();
  }
})();
