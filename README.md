# AI Agents Field Notes

Source for a GitHub Pages site. Articles are written in a private source repository under
`blog/` and copied here for publication.

## Publishing an article

```sh
./sync.sh ../<private-repo>/blog/2026-09-10-dgx-spark-performance.md \
          "Infrastructure" "dgx-spark,llama.cpp,benchmarking"
git add _posts && git commit -m "publish: ..." && git push
```

`sync.sh` writes the front matter (title, date, category, tags), strips the article's
`# H1` — the layout renders the title itself and would otherwise print it twice — and
rewrites links so they resolve against the site: cross-article links become
`/posts/<slug>/`, and links to the diagnostics become `/scripts/<file>`.

## The theme

Vendored, not fetched: `_layouts/`, `_includes/`, `_sass/` and `assets/` are the site,
with no `remote_theme` and no override layer. Upstream is
[Hydrogen](https://github.com/link9596/jekyll-theme-Hydrogen), MIT, and the notice
travels with it in `licenses/hydrogen-MIT.txt`.

It is the same theme as the sibling blog, [The AI SDLC
Memo](https://remwes0608.github.io/ai-driven-sdlc). The two are meant to read as
siblings: one skeleton, one typeface, different colour and different voice. Colour is
what tells them apart — that one is sea-green, this one is greyscale.

Two rules worth knowing before editing it:

- **Every colour is measured.** `assets/css/extra.css` opens with the palette, and each
  token carries its WCAG contrast ratio against the surface it actually sits on. The
  floor is 5.5:1, checked in dark mode as well as light. Where the theme shipped a colour
  that failed, it was changed in `_sass` at source rather than overridden, so one accent
  cannot resurface in a component nobody remembered.
- **`_sass` is ASCII-only.** libsass, which GitHub Pages uses, reads a `_sass` file with
  no `@charset` as US-ASCII and refuses to build on any non-ASCII byte — including one in
  a comment. An em dash in a licence header is enough to break the site.

## One-time setup

1. Create the public repository and push this directory.
2. Settings → Pages → Source: **Deploy from a branch**. The theme is vendored and the
   only plugins are `jekyll-feed`, `jekyll-sitemap` and `jekyll-redirect-from`, all on the
   Pages allowlist, so Pages builds this itself and there is no Actions workflow.
3. Set `url` and `baseurl` in `_config.yml` to match where it lands.

## Working on it locally

```sh
bundle install
bundle exec jekyll serve
```

Then http://localhost:4000/ai-agents-field-notes/ — the `/ai-agents-field-notes` part is
`baseurl`; empty it for a user site or custom domain and the path goes away. Note that
`jekyll serve` does not reload `_config.yml`: restart it after changing that file, or the
change will look as though it did nothing.

## What is generated

| path | what |
| --- | --- |
| `/` | `about.md` — the front page |
| `/posts/` | the articles, newest first |
| `/posts/<slug>/` | an article, with a table of contents beside it above 64em |
| `/about/` | redirects to `/` |
| `/scripts/` | `scripts/README.md`, rendered by `jekyll-readme-index` |
| `/feed.xml`, `/sitemap.xml` | feed and sitemap |

About is the front page rather than the article list: two articles make a thin landing
page, and what a reader arriving cold needs first is what the agent is and what it runs
on. It carries `permalink: /` and `redirect_from: /about/`, because that URL is indexed
and is where both articles point. The band and the share metadata at the root show the
site's own name and description rather than the page's, so someone arriving from a search
learns where they landed before what the page covers. The redirect stub carries no
beacon, so a redirected visit is counted once, at the destination.

The contents list is built by `assets/js/toc.js` from the page's own `h2` elements and
stays hidden below three sections. A post gets it automatically; any other page opts in
with `toc: true`.

## What search engines see

Every indexable page carries a unique title and meta description, a canonical URL, Open
Graph and Twitter card tags, and JSON-LD — `BlogPosting` on an article, `WebSite`
elsewhere. All of it is derived in `_includes/head.html` from the three values a page
already has (title, description, date), so nothing needs maintaining per post.

The share image is `img/card.png`, 1200×630 as the tags declare. It is drawn by
`python3 tools/make-card.py` rather than screenshotted: the same artwork as the title
bands, the site's own Plus Jakarta Sans, and the title laid out to fit rather than trusted
to a viewport — the previous card had been captured at a width that cut it off after "AI
Agents Field No". The script measures both text colours against the brightest pixel behind
them and refuses to write a card under 5.5:1, which is what caught the subtitle sitting at
5.20:1 where the trend line passes through it.

The site's mark is `img/favicon.svg`: three ascending bars, the motif on every title band,
in the palette's greys with the artwork's green on the tallest. `favicon-48.png` and
`apple-touch-icon.png` are the same geometry rasterised. Edit the SVG, then run
`python3 tools/make-icons.py` to redraw the PNGs from the same numbers, so the three cannot
drift apart. The green there is lifted from the artwork's `#2E6B5E` to `#4f9e8a`: the
original measures 2.87:1 against the dark ground, which is legible as a 4px line across a
1600px band and mud at 16px. All three are declared explicitly in the
head, because both blogs share `remwes0608.github.io` and `/favicon.ico` at the domain
root is not this site's to claim.

Two pages are kept out of the index on purpose: `/about/`, which `jekyll-redirect-from`
marks `noindex` so the redirect cannot compete with the page it points at, and the Search
Console verification file, excluded from the sitemap by a `defaults` rule in `_config.yml`
— set there rather than in the file, which has to stay byte-identical.

## Analytics

Cloudflare Web Analytics, emitted at the end of `_layouts/default.html` and only when
`jekyll.environment` is `production` — so local reading under `jekyll serve` is never
counted. It sets no cookies and stores no per-visitor identifier, which is the whole
reason it is here and the reason the site needs no consent banner. It is also the only
third-party request the site makes at all: the typeface is served from `assets/css/` and
the icons are inline SVG, so the beacon is the one thing a reader fetches from anyone
else. The token in `_config.yml` is public by design — it ships in the page source to
every visitor.

Cloudflare keys a site by hostname, so `remwes0608.github.io` is one property covering
both blogs that live there; this site reuses that token and is told apart in the
dashboard by path. Moving to a domain of its own is the only thing that would call for a
second token.

## Licence

Prose and measurements: CC BY 4.0. Code and configuration snippets: MIT. See `LICENSE`.
The vendored theme keeps its own MIT notice in `licenses/hydrogen-MIT.txt`.
