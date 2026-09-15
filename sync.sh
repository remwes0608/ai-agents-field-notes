#!/bin/sh
# Copy an article out of the private source repo into _posts/, adding the
# front matter Clean Blog needs and stripping the H1 (the theme renders the
# title in the hero, so leaving it in prints the heading twice).
#
#   ./sync.sh ../<private-repo>/blog/2026-09-10-dgx-spark-performance.md \
#             "Six configuration changes, each measured the same way"
set -e
SRC="$1"; SUBTITLE="$2"; DESCRIPTION="$3"
[ -f "$SRC" ] || { echo "usage: $0 <article.md> [subtitle] [description]"; exit 1; }
BASE=$(basename "$SRC")
DST="_posts/$BASE"
TITLE=$(sed -n 's/^# //p' "$SRC" | head -1)
esc() { printf '%s' "$1" | sed 's/"/\\"/g'; }
{
  printf -- '---\n'
  printf 'title: "%s"\n' "$(esc "$TITLE")"
  [ -n "$SUBTITLE" ] && printf 'subtitle: "%s"\n' "$(esc "$SUBTITLE")"
  # The meta description search engines show. Without it `head.html` falls back to the excerpt,
  # which is the hook — good prose, but it carries whatever terms the hook happened to use.
  [ -n "$DESCRIPTION" ] && printf 'description: "%s"\n' "$(esc "$DESCRIPTION")"
  printf 'background: "/img/bg-post.svg"\n'
  printf -- '---\n\n'
  # Strip the H1, then rewrite links so they resolve against the site rather
  # than the private repo.
  sed '1{/^# /d;}' "$SRC" \
    | sed '1{/^$/d;}' \
    | sed -E 's|\]\((\./)?[0-9]{4}-[0-9]{2}-[0-9]{2}-([a-z0-9-]+)\.html?\)|]({{ site.baseurl }}/\2/)|g' \
    | sed -E 's|\]\((\./)?[0-9]{4}-[0-9]{2}-[0-9]{2}-([a-z0-9-]+)\.md\)|]({{ site.baseurl }}/posts/\2/)|g' \
    | sed -E 's|\]\((scripts/[A-Za-z0-9_.-]+)\)|]({{ site.baseurl }}/\1)|g' \
    | sed -E 's|\]\(about\.md\)|]({{ site.baseurl }}/)|g'  # About is the front page
} > "$DST"
echo "wrote $DST  <- $TITLE"
