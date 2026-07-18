# MANTICE

## Search Discoverability Roadmap

**Status review:** 18 July 2026
**Canonical website:** https://bassimatte.github.io/mantice/

Mantice now has the technical foundation required for search discovery. The next challenge is not adding more metadata; it is helping Google index the official website, giving the site more useful pages to understand, and building authority around the searches Mantice should answer.

## The central point

Mantice is currently **crawlable**, does not yet appear to be **indexed as the primary result**, and is not yet **ranking competitively** for broader ambient-drone searches.

### Crawlable

The deployed website returns HTTP 200 and now exposes:

- A descriptive page title and meta description
- A canonical homepage URL
- Index and follow directives
- SoftwareApplication structured data
- Open Graph and social sharing metadata
- A public robots.txt file
- A public XML sitemap

### Indexed

Current search checks surface the Elektronauts and Freesound discussions about Mantice, but not the official Mantice homepage. This suggests that Google has either not recrawled the newly optimized page or has not yet selected it as the strongest result.

### Ranking

Technical metadata makes Mantice understandable, but metadata alone does not create search authority. Mantice currently offers a large application through essentially one searchable URL. Its gallery, documentation, shared presets and generator states are useful to people, but they are not independent pages that search engines can discover and rank.

## Phase 1 — Register and measure

### Google Search Console

1. Add a URL-prefix property for https://bassimatte.github.io/mantice/
2. Select HTML-tag verification.
3. Add the supplied verification meta tag to the Mantice homepage.
4. Complete ownership verification.
5. Submit https://bassimatte.github.io/mantice/sitemap.xml
6. Inspect the canonical homepage and request indexing.
7. Review indexing status, rendered HTML and discovered resources.

Search Console is the first priority because it distinguishes a genuine indexing issue from the normal delay between publishing and recrawling.

### Initial search themes to monitor

- free online ambient drone synthesizer
- ambient drone generator
- browser drone synth
- generative ambient music tool
- wavetable drone generator
- granular drone generator

Record impressions, average position and clicks monthly. Early impressions are useful even before clicks arrive because they show which vocabulary Google associates with Mantice.

## Phase 2 — Create useful searchable pages

Keep the application at its current address so existing shared links continue to work. Add static pages around it:

- /mantice/about/
- /mantice/gallery/
- /mantice/docs/
- /mantice/guides/creating-ambient-drones/
- /mantice/guides/wavetable-drone-synthesis/
- /mantice/presets/breathing-cathedral/
- /mantice/presets/warpy-cherry-leviathan/

Each page should have a unique title, description, canonical URL, visible introductory copy and real links to related pages. Avoid creating thin pages that merely repeat keywords.

## Phase 3 — Turn presets into a discovery surface

The preset library is Mantice’s strongest scalable search asset. Static preset pages can be generated automatically from the existing YAML metadata.

Each preset page should contain:

- Preset name and original description
- Category, mood and tags
- Synthesis engines and layer summary
- Root frequency, tuning and movement character
- Sonic fingerprint
- Short audio preview where available
- Remix lineage and related presets
- A clear Open in Mantice action

This creates useful pages for specific sound-design intentions without manufacturing generic SEO content. It also gives gallery entries stable URLs that can be linked from Freesound, Elektronauts, CarveToy and social posts.

## Phase 4 — Publish two authoritative guides

### How to Create Deep, Evolving Ambient Drones

Cover slow modulation, complementary layers, tuning, stereo movement, reverb, headroom and the difference between motion and distraction. Use Mantice presets as audible examples.

### How to Turn a Wavetable into an Ambient Drone

Cover wavetable selection, narrow scan regions, slow scan rates, filtering and the use of FM and subtractive layers to create body beneath spectral movement. Connect the guide naturally to CarveToy and Mantice’s wavetable importer.

The goal is not to start a high-volume blog. Two original, technically useful resources are more valuable than many shallow posts.

## Phase 5 — Strengthen relevant external signals

Mantice already has relevant discussions that search engines surface. Improve those existing references before pursuing generic promotion:

- Update the first Freesound post with the current four-engine description.
- Update the Elektronauts post, removing the outdated “three engines” and “no samples” wording.
- Link to Mantice using descriptive language such as “free online ambient drone synthesizer.”
- Ask CarveToy to mention Mantice as a creative destination for its wavetables.
- Keep the GitHub repository description, homepage link and topic tags accurate.
- Share individual preset pages when discussing specific sounds rather than always linking only to the homepage.

Do not buy links, exchange unrelated links or publish keyword-filled copies of the same article.

## Custom domain decision

A memorable domain such as mantice.audio could improve branding, recall and link sharing. It is not the immediate ranking priority. If adopted, it should be configured once, treated as the canonical address and migrated carefully so existing GitHub Pages URLs redirect to it.

Evaluate a custom domain after Search Console is active and the first static discovery pages exist.

## Recommended sequence

### Now

1. Verify Mantice in Google Search Console.
2. Submit the sitemap and request homepage indexing.
3. Update the Freesound and Elektronauts introductions.

### Next build

4. Generate static gallery and preset pages from the preset metadata.
5. Add crawlable navigation between the homepage, gallery, documentation and preset pages.

### Then

6. Publish the two definitive ambient-drone guides.
7. Pursue a small number of relevant community and creator links.
8. Evaluate a custom domain.

## Measures of progress

Review these indicators over four to six weeks:

- Homepage indexed under the canonical URL
- Mantice appearing first for branded searches
- Impressions for ambient-drone and browser-synth queries
- Number of indexed gallery, guide and preset pages
- Click-through rate from search results
- External links from relevant music and sound-design communities
- Visitors who move from a guide or preset page into the instrument

The immediate objective is not to rank for every broad synthesizer query. It is to make Mantice unmistakably discoverable for its name and highly relevant niche: free, browser-based creation of large, evolving ambient drones.

## Reference links

- Mantice: https://bassimatte.github.io/mantice/
- Sitemap: https://bassimatte.github.io/mantice/sitemap.xml
- Source repository: https://github.com/bassimatte/mantice
- Google Search Console guidance: https://developers.google.com/search/docs/monitor-debug/search-console-start
- Google SEO Starter Guide: https://developers.google.com/search/docs/fundamentals/seo-starter-guide
- Google sitemap guidance: https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap
- Freesound discussion: https://freesound.org/forum/production-techniques-music-gear-tips-and-tricks/45448/
- Elektronauts discussion: https://www.elektronauts.com/t/mantice-ambient-drone-generator/251568
