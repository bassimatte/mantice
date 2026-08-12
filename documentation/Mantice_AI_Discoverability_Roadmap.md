# MANTICE AI Discoverability Roadmap

## Objective

Make MANTICE easier to discover, understand, and cite through AI-assisted search products such as ChatGPT Search, while improving conventional search visibility at the same time.

There is no guaranteed mechanism for inclusion in an AI answer. The practical goal is to make MANTICE crawlable, clearly described, well structured, and corroborated by independent public sources.

## Current position

MANTICE is already technically available to search crawlers:

- The public site is accessible without authentication.
- `robots.txt` allows crawling.
- `sitemap.xml` identifies the canonical homepage.
- The homepage declares its canonical URL.
- The homepage includes `SoftwareApplication` structured data.
- Google Search Console ownership is configured.

OpenAI documents two separate crawlers:

- `OAI-SearchBot` is used to surface sites in ChatGPT search results.
- `GPTBot` relates to possible use of crawled content for improving generative AI foundation models.

These controls are independent. Allowing `OAI-SearchBot` is the relevant requirement for ChatGPT Search visibility; allowing `GPTBot` is not a ranking mechanism.

Official reference: <https://developers.openai.com/api/docs/bots>

## Primary limitation

MANTICE currently presents most of its public information through one large application URL. The interface contains substantial information, but search and answer systems have only one page to classify and cite.

Crawler access alone does not make a site likely to appear in an answer. MANTICE needs focused, indexable pages that answer the questions potential users actually ask.

## Recommended indexable pages

Create a small documentation website linked from the application:

1. `/about/`
   - What MANTICE is
   - Who it is for
   - What makes it distinct
   - License, creator, and source repository

2. `/features/`
   - FM synthesis
   - Subtractive synthesis
   - Granular synthesis
   - Wavetable synthesis
   - Spatial motion, effects, generation, rendering, and sharing

3. `/ambient-drone-generator/`
   - What an ambient drone generator does
   - How MANTICE creates evolving sounds
   - Generator, mutation, and preset workflows

4. `/wavetable-drone-synth/`
   - WAV wavetable import
   - Frame scanning
   - Scan waveform and direction
   - Smooth random, tremor, audio-rate scanning, and unison

5. `/guides/getting-started/`
   - Load a preset
   - Start audio
   - Modify layers
   - Generate, mutate, render, and share

6. `/guides/local-rendering/`
   - Local browser interface
   - Python installation
   - Long and high-resolution exports

7. `/faq/`
   - Direct answers to common questions
   - Visible FAQ content with matching structured data

Every page should have a unique title, meta description, canonical URL, visible heading, internal links, and an entry in `sitemap.xml`.

## Content principles

### State the core identity plainly

Use a stable description throughout the website, repository, Freesound, and public posts:

> MANTICE is a free, open-source ambient drone synthesizer that runs in a web browser. It combines FM, subtractive, granular, and wavetable synthesis to create evolving soundscapes.

### Answer real questions

Create visible sections around questions such as:

- What is a free browser-based drone synthesizer?
- How can I create an ambient drone online?
- How can I generate a drone from a WAV wavetable?
- What is slow wavetable scanning?
- How do I make a drone evolve without fast modulation?
- What is the difference between FM, granular, subtractive, and wavetable layers?
- How can I render a long ambient drone locally?

Use the question as a heading, followed immediately by a concise factual answer. Add depth below it where useful.

### Keep important information in visible HTML

Do not rely exclusively on controls, modal windows, canvas graphics, or dynamically generated text. Core explanations should be present in crawlable HTML and usable without interacting with the synthesizer.

### Demonstrate instead of only claiming

Include concrete examples:

- Embedded or linked audio demonstrations
- Screenshots with descriptive alternative text
- Named workflows
- Public presets
- Short explanations of how particular sounds were made
- Links to matching Freesound releases

## Structured data

Extend the existing `SoftwareApplication` data with stable public facts where appropriate:

- Name and alternate name
- Canonical application URL
- Description
- Application category and operating system
- Free offer
- License
- Creator
- Source-code repository
- Documentation URL
- Screenshot
- Current software version
- `sameAs` links to authoritative MANTICE profiles

Add `FAQPage` structured data only when the same questions and answers are visibly present on the FAQ page.

Structured data helps systems understand the entity, but it does not replace high-quality visible content.

## External corroboration

AI-assisted search is more likely to trust and cite a project that is consistently described by multiple public sources.

Useful sources include:

- The GitHub repository and README
- Freesound packs and individual sound descriptions
- The Freesound forum announcement
- Sound-design and music-production forums
- Tutorials or blog posts
- Curated open-source audio-software lists
- Videos demonstrating specific workflows

Use a consistent name and description, and link back to the canonical MANTICE website. Prefer useful demonstrations and tutorials over repetitive promotional posts.

## `robots.txt` policy

The existing general allow rule already permits OpenAI's crawlers. Explicit rules may be added for clarity:

```text
User-agent: OAI-SearchBot
Allow: /

User-agent: GPTBot
Allow: /

User-agent: *
Allow: /

Sitemap: https://bassimatte.github.io/mantice/sitemap.xml
```

The `GPTBot` choice is optional and should reflect the desired training policy. It is independent from ChatGPT Search eligibility.

If hosting or firewall rules are introduced later, ensure that requests from OpenAI's published search-crawler IP ranges are not blocked.

## `llms.txt`

An optional `/llms.txt` could provide:

- A one-paragraph description of MANTICE
- Canonical links to About, Features, Guides, FAQ, and source code
- A concise list of synthesis capabilities

This is an emerging convention rather than an official ChatGPT Search requirement. It should be treated as a supplementary navigation aid, not a substitute for indexable HTML, a sitemap, or crawler access.

## Measurement

Use Google Search Console to monitor:

- Indexed pages
- Search queries
- Impressions and clicks
- Click-through rate
- Mobile versus desktop visibility
- Branded versus non-branded discovery

Use privacy-conscious web analytics to monitor what happens after arrival:

- Visitors who start audio
- Preset loading
- Generator and mutation usage
- Wavetable feature adoption
- Gallery auditions
- Rendering and sharing
- Failures in important workflows

Do not infer AI-search visibility solely from crawler logs. Look for referrals from AI search products where available, increases in branded queries, and independent mentions or citations.

## Implementation order

### Phase 1 — Foundation

1. Keep `OAI-SearchBot` allowed.
2. Complete Google Search Console verification and sitemap submission.
3. Create About, Features, Getting Started, and FAQ pages.
4. Expand `sitemap.xml`.
5. Link the new pages from the application and README.

### Phase 2 — Subject authority

1. Create focused ambient-drone and wavetable guides.
2. Add audio examples and useful screenshots.
3. Improve structured data.
4. Publish consistent Freesound descriptions and forum resources.
5. Seek relevant independent listings and tutorials.

### Phase 3 — Optional AI support

1. Add `/llms.txt` as a concise documentation map.
2. Review crawler access periodically.
3. Update pages when features change.
4. Measure AI referrals and branded discovery where available.

## Success criteria

- Google indexes all intended documentation pages.
- Search Console begins showing relevant non-branded queries.
- MANTICE is discoverable for browser drone synthesizer and wavetable-drone questions.
- External sources describe MANTICE consistently and link to its canonical site.
- ChatGPT Search and other answer systems can retrieve a concise, factual page directly relevant to the user's question.
