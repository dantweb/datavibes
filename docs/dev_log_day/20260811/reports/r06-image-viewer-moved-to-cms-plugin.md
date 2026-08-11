# R06 — The image viewer belongs in the CMS plugin, not in each page

**Date:** 2026-08-11 · **Type:** design decision + deploy record · **Status:** done

## The question

The dataset landing pages ([R05](r05-publish-to-vbwd-cc.md)) shipped a CSS-only
lightbox baked into each page's `content_html`. Should that move to the CMS
plugin so *every* image in CMS-authored body copy is zoomable?

## Decision: yes — but there are FOUR render paths, not one

CMS body copy reaches a page through four separate `v-html` renderers in
`vbwd-fe-user-plugin-cms`. They must all behave the same, so the behaviour lives
in one composable (`useImageZoom`) plus one presentational component
(`ImageLightbox`), and each path has its own spec:

| Renderer | Renders | Spec |
|---|---|---|
| `CmsLayoutRenderer` (content area) | **every laid-out page and post** — the live path | `CmsLayoutRenderer.lightbox.spec.ts` |
| `CmsPageTypeBase` (`<article>`) | a page with **no** layout (fallback only) | `CmsPageTypeBase.lightbox.spec.ts` |
| `CmsWidgetRenderer` (html widget) | html widgets inside a layout | `CmsWidgetRenderer.lightbox.spec.ts` |
| `RichTextBlock` | `richtext` blocks + **entity pages** (dataset landings) | `RichTextBlock.lightbox.spec.ts` |

## What the component buys that CSS could not

The page body reaches the browser through `v-html`, and **a `<script>` inserted
that way is never executed** — so the per-page version *had* to be CSS-only
(`:target` + sibling radios + `overflow: auto`). As a component it gains Escape
to close, `+`/`-` to zoom, focus moved to the close button and restored
afterwards, body scroll locked while open, no history/URL pollution, and
drag-to-pan for mouse users. It also declines images that shouldn't zoom: one
inside a link keeps the author's intent, `data-nozoom` opts out, and anything
under 80px reads as an icon.

## Three deploys, and why

**Each of the first two deployed green and changed nothing on the live site.**

1. `1ea6e2e` — wired `RichTextBlock`, reasoning that it is registered as the
   `richtext` post content type. Entity pages worked; **posts did not**, because
   post bodies never take that path.
2. `45a0704` — added `CmsWidgetRenderer`, assuming post bodies were html
   widgets. Still nothing: a live post's images were the link-wrapped logo
   (correctly excluded) and the hero.
3. `e3a1d43` — added `CmsPageTypeBase`… but that component renders
   `v-if="layout"` → `CmsLayoutRenderer` and only falls back to its own
   `<article>` when a page has **no** layout. Every live page has a layout, so
   this wired a branch production never executes.
4. `cc212c1` — `CmsLayoutRenderer`'s content area. **This is the one that
   reached production.**

The method that actually found the answer, each time, was parsing the **live
DOM's ancestor chain** for each image rather than reading the code and inferring
which component "looked" authoritative. Registration in a registry is not proof
of the render path.

Also added `stopPropagation` when the viewer opens: the containers nest (layout
body > html widget) and both delegate, so without it a single click could open
two overlays.

## Verified live

| Page | images | zoomable |
|---|---:|---:|
| `blog/…/non-custodial-crypto-payments…` | 7 | 6 |
| `blog/…/own-your-data-gdpr-first…` | 3 | 2 |
| `blog/…/build-telegram-ecommerce…` | 3 | 2 |
| `data-store/…/oss-project-health` | 6 | 5 |
| `data-store/…/carbon-emissions-trajectory` | 6 | 5 |
| `data-store/…/power-price-volatility` | 6 | 5 |

Exactly one image per page is excluded every time — the link-wrapped site logo,
which is correct by design.

Gate before each push: full fe-user unit suite (**1 982** at the end, 21 new)
and `vue-tsc --noEmit`, which caught two errors that would otherwise have failed
the production build (`npm run build:check` = `vue-tsc --noEmit && vite build`).

Shipped via `VBWD-platform/vbwd-demo-instances` → "Deploy VBWD Demo Instances"
(`deploy_main=true`, siblings false, `run_migrations=false`). One run failed on
`ssh: Connection timed out` — pure infrastructure; vbwd.cc stayed healthy on the
prior image, and re-running only the failed job (images already in GHCR)
succeeded.

## Migration

The generator grew `--no-lightbox`, dropping the per-page CSS viewer, its
trigger anchors and its ~4.8 KB of now-dead CSS while leaving images untouched
(pages fell from ~26.7 KB to ~19.0 KB). Applied **after** the first deploy was
verified live, so there was never a window with neither viewer.
