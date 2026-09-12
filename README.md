# AI Agents Field Notes

Source for a GitHub Pages site built with the [Chirpy](https://github.com/cotes2020/jekyll-theme-chirpy)
theme. Articles are written in a private source repository under `blog/`
and copied here for publication.

## Publishing an article

```sh
./sync.sh ../<private-repo>/blog/2026-09-10-dgx-spark-performance.md \
          "Infrastructure" "dgx-spark,llama.cpp,benchmarking"
git add _posts && git commit -m "publish: ..." && git push
```

`sync.sh` writes the Chirpy front matter (title, date, category, tags, `toc`),
strips the article's `# H1` — the theme renders the title itself and would
otherwise print it twice — and rewrites links so they resolve against the site:
cross-article links become `/posts/<slug>/`, and links to the diagnostics become
`/scripts/<file>`.

## One-time setup

1. Create the public repository and push this directory.
2. Settings → Pages → Source: **GitHub Actions** (not "Deploy from a branch" —
   Chirpy needs Jekyll 4 and plugins outside the Pages allowlist, so it is built
   by `.github/workflows/pages-deploy.yml`).
3. Set `url` and `baseurl` in `_config.yml` to match where it lands.

## Working on it locally

```sh
bundle install
bundle exec jekyll serve --livereload
```

Then http://localhost:4000/ai-agents-field-notes/ — the `/ai-agents-field-notes` part is
`baseurl`; empty it for a user site or custom domain and the path goes away.

## What is generated

| path | what |
| --- | --- |
| `/` | post index, newest first |
| `/posts/<slug>/` | an article, with a sidebar table of contents |
| `/categories/`, `/tags/` | generated indexes |
| `/about/` | `_tabs/about.md` |
| `/feed.xml`, `/sitemap.xml` | feed and sitemap |

## Licence

Prose and measurements: CC BY 4.0. Code and configuration snippets: MIT. See `LICENSE`.
