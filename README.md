# AI Agents Field Notes

Source for a GitHub Pages site. Articles are written in a private repository under `blog/`
and copied here for publication.

## Publishing an article

```sh
./sync.sh ../<private-repo>/blog/2026-09-10-dgx-spark-performance.md \
          "Infrastructure" "dgx-spark,llama.cpp,benchmarking"
git add _posts && git commit -m "publish: ..." && git push
```

`sync.sh` writes the front matter, strips the article's `# H1` — the layout renders the
title itself and would otherwise print it twice — and rewrites links to resolve against
the site.

## Working on it locally

```sh
bundle install
bundle exec jekyll serve
```

Then <http://localhost:4000/ai-agents-field-notes/>, where that path is `baseurl` — empty
it in `_config.yml` for a user site or custom domain. Note that `jekyll serve` does **not**
reload `_config.yml`: restart it after changing that file, or the change will look as
though it did nothing.

Pages builds the site itself from the branch. The theme is vendored and the only plugins —
`jekyll-feed`, `jekyll-sitemap`, `jekyll-redirect-from` — are on the Pages allowlist, so
there is no Actions workflow to maintain.

## What is generated

| path | what |
| --- | --- |
| `/` | `about.md` — the front page |
| `/posts/` | the articles, newest first |
| `/posts/<slug>/` | an article, with a table of contents beside it above 64em |
| `/about/` | redirects to `/` |
| `/scripts/` | `scripts/README.md`, via `jekyll-readme-index` |
| `/feed.xml`, `/sitemap.xml` | feed and sitemap |

About is the front page rather than the article list: two articles make a thin landing
page. It carries `permalink: /` and `redirect_from: /about/`, because that URL is indexed
and is where both articles point. At the root, the title band and the share tags show the
site's name and description rather than the page's.

`assets/js/toc.js` builds the contents from a page's own `h2` elements, and hides it below
three sections. A post gets it automatically; any other page opts in with `toc: true`.

## The theme

Vendored, not fetched: `_layouts/`, `_includes/`, `_sass/` and `assets/` are the site, with
no `remote_theme` and no override layer. Upstream is
[Hydrogen](https://github.com/link9596/jekyll-theme-Hydrogen), MIT.

It is the same theme as the sibling blog, [The AI SDLC
Memo](https://remwes0608.github.io/ai-driven-sdlc) — one skeleton and one typeface,
different colour and different voice. That one is sea-green; this one is greyscale.

Two rules before editing it:

- **Every colour is measured.** `assets/css/extra.css` opens with the palette, each token
  carrying its contrast ratio against the surface it sits on. The floor is 5.5:1, in dark
  mode as well as light. Where the theme shipped a colour that failed, it was fixed at
  source in `_sass` rather than overridden, so a stray accent cannot resurface in some
  component nobody remembered. Code needs a separate token set per scheme, because no one
  colour can clear the floor on both the light and the dark code block — the arithmetic is
  in `extra.css`.
- **`_sass` is ASCII-only.** libsass, which Pages uses, reads a `_sass` file with no
  `@charset` as US-ASCII and refuses to build on any non-ASCII byte — including one in a
  comment. An em dash in a licence header is enough to break the site.

## Images and search metadata

`_includes/head.html` derives each page's title, description, canonical URL, Open Graph,
Twitter card and JSON-LD from values the page already has, so none of it is maintained per
post.

Two assets are generated rather than drawn by hand. Edit the source, then re-run:

```sh
python3 tools/make-card.py    # img/card.png, the 1200x630 link preview
python3 tools/make-icons.py   # the PNG icons, redrawn from img/favicon.svg
```

Both refuse to produce something unreadable — the card script measures its text against the
brightest pixel behind it and fails below 5.5:1. The favicon's green is lifted from the
artwork's `#2E6B5E` to `#4f9e8a`, which the original is too dark to survive at 16px. The
icons are declared explicitly in the head because both blogs share `remwes0608.github.io`,
so `/favicon.ico` at the domain root is not this site's to claim.

Two pages stay out of the index deliberately: `/about/`, which `jekyll-redirect-from` marks
`noindex` so the redirect cannot compete with the page it points at, and the Search Console
verification file, excluded from the sitemap by a `defaults` rule in `_config.yml` — set
there because the file itself has to stay byte-identical.

## Analytics

Cloudflare Web Analytics, emitted at the end of `_layouts/default.html` and only when
`jekyll.environment` is `production`, so local reading is never counted. It is cookieless
and stores no per-visitor identifier, which is why the site needs no consent banner — and
it is the only third-party request the site makes, since the typeface is served locally and
the icons are inline SVG. The token in `_config.yml` is public by design.

Cloudflare keys a site by hostname, so `remwes0608.github.io` is one property covering both
blogs that live there; this one reuses that token and is told apart by path. Only moving to
a domain of its own would call for a second.

## Licence

Prose and measurements: CC BY 4.0. Code and configuration snippets: MIT. See `LICENSE`.

The vendored parts keep their own terms, and both notices have to travel with them:

| what | licence |
| --- | --- |
| the theme | MIT — `licenses/hydrogen-MIT.txt` |
| Plus Jakarta Sans, `assets/css/*.ttf` | SIL OFL 1.1 — `licenses/PlusJakartaSans-OFL.txt` |

The OFL is why the fonts are served from `assets/css/` rather than pulled from a CDN and
forgotten: redistributing them is allowed, and this is what doing it properly requires.
