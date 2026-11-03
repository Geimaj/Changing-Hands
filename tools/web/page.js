/* Runs on every content page: scroll to the requested record and highlight
   search words passed after "~" in the address, e.g. p00012.html#r345~smith */
(function () {
  'use strict';
  var VARIANTS = { a: 'aàáâãäå', e: 'eèéêë', i: 'iìíîï', o: 'oòóôõö', u: 'uùúûü', c: 'cç', n: 'nñ', y: 'yýÿ' };
  function pattern(w) {
    return w.split('').map(function (ch) {
      var v = VARIANTS[ch];
      return v ? '[' + v + ']' : ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('');
  }
  function mark(root, words) {
    var re = new RegExp('(' + words.filter(function (w) { return w.length > 1; }).map(pattern).join('|') + ')', 'gi');
    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
    var nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(function (t) {
      if (!re.test(t.data)) return;
      re.lastIndex = 0;
      var span = document.createElement('span');
      span.innerHTML = t.data.replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; })
        .replace(re, '<mark>$1</mark>');
      t.parentNode.replaceChild(span, t);
    });
  }
  function go() {
    var h = decodeURIComponent(location.hash.slice(1));
    if (!h) return;
    var parts = h.split('~');
    var el = document.getElementById(parts[0]);
    if (!el) return;
    var rec = el.closest('.rec') || el;
    rec.classList.add('target');
    if (parts[1]) mark(rec, parts[1].split(/\s+/));
    el.scrollIntoView({ block: 'start' });
  }
  window.addEventListener('hashchange', go);
  go();
})();
