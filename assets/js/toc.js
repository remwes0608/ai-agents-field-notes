/* Table of contents, built from the h2s already in the post.
   Nothing is maintained per article, and a post with fewer than three sections keeps its
   contents hidden — a two-item list is furniture, not navigation. */
(function () {
  var article = document.getElementById('post-body');
  var toc = document.getElementById('post-toc');
  if (!article || !toc) return;

  var headings = Array.prototype.slice.call(article.querySelectorAll('h2'));
  if (headings.length < 3) return;

  var list = toc.querySelector('ol');
  var items = [];

  headings.forEach(function (h, i) {
    if (!h.id) h.id = 'section-' + i;
    var li = document.createElement('li');
    var a = document.createElement('a');
    a.href = '#' + h.id;
    a.textContent = h.textContent;
    li.appendChild(a);
    list.appendChild(li);
    items.push(li);
  });

  toc.hidden = false;

  /* Mark the section being read: the last heading that has passed under the bar. An
     IntersectionObserver is the tidier tool and the wrong one here — once a heading scrolls out
     of its band nothing is intersecting, so the middle of a long section would highlight
     nothing at all. */
  var current = -1;
  var ticking = false;

  function update() {
    ticking = false;
    var i = 0;
    for (var n = 0; n < headings.length; n++) {
      if (headings[n].getBoundingClientRect().top <= 90) i = n; else break;
    }
    if (i === current) return;
    if (current >= 0) items[current].classList.remove('is-current');
    items[i].classList.add('is-current');
    current = i;
  }

  window.addEventListener('scroll', function () {
    if (ticking) return;
    ticking = true;
    window.requestAnimationFrame(update);
  }, { passive: true });

  update();
})();
