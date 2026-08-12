# MANTICE Umami Analytics

## Purpose

Measure aggregate adoption and reliability of MANTICE's major workflows without collecting sound-design data or tracking local users.

The questions this setup should answer are:

- How many visitors actually start audio?
- Do people use official presets, community presets, or the gallery?
- Which major synthesis types are enabled when generation succeeds?
- How often are Generate, Mutate, Gallery, Wavetable, Render, Share, and the guides used?
- Which export formats and quality levels are completed?

It is not intended to reconstruct individual identities or collect preset content.

## Privacy boundary

Analytics is enabled only when both the hostname and project path match:

```text
bassimatte.github.io/mantice/
```

It is disabled on local installations, repository forks, preview deployments, and locally opened files. The Umami tracker is not loaded at all on those hosts.

The application does not send:

- Preset names or IDs
- Shared-preset links
- Creator names
- Slider or parameter values
- Imported filenames or file contents
- Audio, samples, or wavetables
- Freesound search queries
- Free-form user text
- Exact error messages
- Identifiers supplied by MANTICE

Every custom property is checked against an explicit allowlist before being sent. URL query strings and fragments are excluded, and the tracker respects the browser's Do Not Track setting.

Do not enable Umami session replay or heatmaps for MANTICE. They are unnecessary for aggregate product analytics and would expand the privacy surface.

## Events

| Event | Meaning | Allowed properties |
|---|---|---|
| `audio_started` | Audio successfully began playing | `source`, `playback` |
| `preset_loaded` | A preset was successfully loaded | `source`, `category` |
| `generator_completed` | Generation returned a usable result | `mood`, four synthesis-type toggles |
| `candidate_selected` | A generated candidate was selected | `texture` |
| `mutation_completed` | Mutation returned a usable result | `amount` bucket |
| `gallery_opened` | The gallery was opened | `sort` |
| `gallery_auditioned` | A gallery or candidate preview began | `kind` |
| `gallery_favorite_changed` | A local favorite was added or removed | `action` |
| `wavetable_action` | A built-in table was chosen, a WAV import succeeded, or an external creation/search resource was opened | `method` |
| `render_completed` | Audio was rendered and downloaded successfully | `format`, `quality`, duration bucket, normalization state |
| `preset_file_action` | A preset file import or export completed | `action` |
| `preset_shared` | A share link was copied or a new shared preset was uploaded | `mode`, `source` |
| `guide_completed` | A guide reached its completion path | `guide` |

Events represent completed outcomes where practical, not mere button presses. High-frequency controls such as sliders are deliberately excluded.

## Umami Cloud setup

1. Create a free Umami Cloud Hobby account at <https://cloud.umami.is/signup>.
2. Choose the **EU** data region.
3. Add a website named `MANTICE` with domain:

   ```text
   bassimatte.github.io
   ```

4. In **Settings → Websites**, edit MANTICE and copy its Website ID. This UUID is public tracker configuration, not an API key.
5. Replace the empty value of `MANTICE_UMAMI_WEBSITE_ID` in both:
   - `engine/static/index.html`
   - `docs/index.html`
6. Do not add an Umami API key to the repository or browser code.
7. Do not enable session replay or heatmaps.
8. Deploy, open the public MANTICE page, and verify a page view in Umami's realtime view.

The code dynamically loads the official `https://cloud.umami.is/script.js` tracker only when both the Website ID and canonical hostname are valid. Search parameters and URL fragments are excluded from automatic page views.

Official references:

- <https://docs.umami.is/docs/tracker-configuration>
- <https://docs.umami.is/docs/track-events>
- <https://docs.umami.is/docs/cloud/faq>

## Suggested reports

Start with these event counts:

1. `audio_started`
2. `preset_loaded`
3. `generator_completed`
4. `mutation_completed`
5. `gallery_opened`
6. `wavetable_action`
7. `render_completed`
8. `preset_shared`

Suggested first funnel:

```text
Pageview
  → preset_loaded
  → audio_started
  → generator_completed or mutation_completed
  → render_completed or preset_shared
```

Useful breakdown properties include `source`, `category`, `mood`, `wavetable`, `method`, `format`, `quality`, `duration`, and `mode`.

## Interpretation cautions

- Privacy-preserving visitor and session counts are approximate, not persistent user accounts.
- Browser privacy tools and content blockers will reduce measured traffic.
- Visitors using local Python or browser installations remain deliberately invisible.
- Event counts are not the same as unique people.
- The privacy notice should disclose the use of anonymous, cookieless Umami analytics even when a consent banner is not required.
