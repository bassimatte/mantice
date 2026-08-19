# MANTICE Umami Analytics

## Purpose

Measure aggregate adoption and reliability of MANTICE's major workflows without collecting sound-design data or tracking local users.

The questions this setup should answer are:

- How many visitors actually start audio?
- How quickly does audio begin, and how many sessions keep listening for 30 seconds, 2 minutes, or 5 minutes?
- Do people use official presets, community presets, or the gallery?
- Which major synthesis types are enabled when generation succeeds?
- Where do Generate, Mutate, Render, Share, and Wavetable upload workflows fail?
- Which deeper sound-design features are adopted at least once in a page session?
- How often are Gallery, sample sourcing, Wavetable, guides, and Journeys used?
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
- Exact startup times or continuous interaction traces
- Identifiers supplied by MANTICE

Every custom property is checked against an explicit allowlist before being sent. URL query strings and fragments are excluded, and the tracker respects the browser's Do Not Track setting.

Every MANTICE page view and custom event is tagged `mantice` through Umami's tracker-level `data-tag` setting. Custom event names also use the `mantice_` prefix. Together, these keep MANTICE traffic separate from Campana and any other application reporting into the same Umami account.

Do not enable Umami session replay or heatmaps for MANTICE. They are unnecessary for aggregate product analytics and would expand the privacy surface.

## Events

| Event | Meaning | Allowed properties |
|---|---|---|
| `mantice_audio_started` | Audio successfully began playing | `source`, `playback`, coarse `startup` bucket |
| `mantice_playback_milestone` | Continuous playback reached a once-per-page milestone | `duration`, `source` |
| `mantice_preset_loaded` | A preset was successfully loaded | `source`, `category` |
| `mantice_generator_completed` | Generation returned a usable result | `mood`, four synthesis-type toggles |
| `mantice_candidate_selected` | A generated candidate was selected | `texture` |
| `mantice_mutation_completed` | Mutation returned a usable result | `amount` bucket |
| `mantice_gallery_opened` | The gallery was opened | `sort` |
| `mantice_gallery_auditioned` | A gallery or candidate preview began | `kind` |
| `mantice_gallery_favorite_changed` | A local favorite was added or removed | `action` |
| `mantice_wavetable_action` | A built-in table was chosen, a WAV import succeeded, or an external creation/search resource was opened | `method` |
| `mantice_sample_action` | A built-in sample or Freesound source was selected for a granular layer | `method` |
| `mantice_render_completed` | Audio was rendered and downloaded successfully | `format`, `quality`, duration bucket, normalization state |
| `mantice_preset_file_action` | A preset file import or export completed | `action` |
| `mantice_preset_shared` | A share link was copied or a new shared preset was uploaded | `mode`, `source` |
| `mantice_workflow_started` | A major product workflow was intentionally started | `workflow` |
| `mantice_workflow_failed` | A major workflow ended at a known failure boundary | `workflow`, coarse `reason` bucket |
| `mantice_feature_used` | A deeper feature was first used in the current page session | `feature` |
| `mantice_guide_started` | A guide opened | `guide` |
| `mantice_guide_completed` | A guide reached its completion path | `guide` |
| `mantice_journey_action` | A Journey preview, stream, or render successfully started/completed as appropriate | `action` |

Events represent completed outcomes where practical. The two funnel events deliberately record the start and failure boundary of five major workflows; cancellations are not failures. Playback milestones and feature adoption are emitted at most once per milestone or feature in a page session. High-frequency controls such as sliders are deliberately excluded.

## Umami Cloud setup

1. Create a free Umami Cloud Hobby account at <https://cloud.umami.is/signup>.
2. Choose the **EU** data region.
3. Add a website named `MANTICE` with domain:

   ```text
   bassimatte.github.io
   ```

4. In **Settings → Websites**, edit MANTICE and copy its Website ID. This UUID is public tracker configuration, not an API key.
5. Confirm that `MANTICE_UMAMI_WEBSITE_ID` contains the public Website ID, `MANTICE_ANALYTICS_TAG` is `mantice`, and `MANTICE_ANALYTICS_EVENT_PREFIX` is `mantice_` in both:
   - `engine/static/index.html`
   - `docs/index.html`
6. Do not add an Umami API key to the repository or browser code.
7. Do not enable session replay or heatmaps.
8. Deploy, open the public MANTICE page, and verify a page view in Umami's realtime view.

The code dynamically loads the official `https://cloud.umami.is/script.js` tracker only when both the Website ID and canonical hostname are valid. It attaches `data-tag="mantice"` to the tracker and prefixes custom event names with `mantice_`, while search parameters and URL fragments are excluded from automatic page views.

Official references:

- <https://docs.umami.is/docs/tracker-configuration>
- <https://docs.umami.is/docs/track-events>
- <https://docs.umami.is/docs/cloud/faq>

## Suggested reports

Start with these event counts:

1. `mantice_audio_started`
2. `mantice_preset_loaded`
3. `mantice_generator_completed`
4. `mantice_mutation_completed`
5. `mantice_gallery_opened`
6. `mantice_wavetable_action`
7. `mantice_render_completed`
8. `mantice_preset_shared`
9. `mantice_playback_milestone`
10. `mantice_workflow_failed`
11. `mantice_feature_used`

Suggested first funnel:

```text
Pageview
  → mantice_preset_loaded
  → mantice_audio_started
  → mantice_generator_completed or mantice_mutation_completed
  → mantice_render_completed or mantice_preset_shared
```

Useful breakdown properties include `source`, `startup`, `category`, `mood`, `wavetable`, `method`, `workflow`, `reason`, `feature`, `format`, `quality`, `duration`, and `mode`.

Build separate conversion funnels for each major workflow:

```text
mantice_workflow_started (filter by workflow)
  → its matching completion event
```

Compare matching `mantice_workflow_failed` counts by the same `workflow` and coarse `reason`. Do not sum every workflow into a single conversion rate: Generate, Render, Share, and Wavetable upload have different user intent and completion costs.

For retention of attention rather than return visits, compare `mantice_audio_started` with the `30s`, `2m`, and `5m` `mantice_playback_milestone` buckets. These milestones require uninterrupted playback and are emitted only once per page session.

When the Umami account contains multiple applications, filter reports by tag `mantice` before interpreting MANTICE adoption or workflow counts.

## Interpretation cautions

- Privacy-preserving visitor and session counts are approximate, not persistent user accounts.
- Browser privacy tools and content blockers will reduce measured traffic.
- Visitors using local Python or browser installations remain deliberately invisible.
- Event counts are not the same as unique people.
- The privacy notice should disclose the use of anonymous, cookieless Umami analytics even when a consent banner is not required.
