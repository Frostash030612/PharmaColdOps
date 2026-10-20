# English cinematic concept film

2026-10-20. A new **150-second** film follows the user's six-shot business-pain / value-proposition storyboard. All on-screen text and notes are English. No Kling or other video-generation model was used. The earlier 90-second explainer and both five-minute visual drafts remain unchanged.

## Delivery

Local folder: `data/processed/cinematic-20261020/final-v1/delivery/`.
The adjacent `PharmaColdOps-English-Cinematic-Film.zip` contains exactly six files:

| File | Purpose |
|---|---|
| `PharmaColdOps-Cinematic-Concept-Film-English.mp4` | 150.00 seconds, 1920×1080, 30fps, 4,500 frames, H.264 + AAC; approximately 124 MiB |
| `Poster.png` | Frame extracted from the final encoded film at 85 seconds |
| `English-On-Screen-Notes.srt` | English screen notes, not a speech transcript |
| `Storyboard.en.json` | Six scenes, timings, notes and scope |
| `README.md` | English viewing and scope instructions |
| `manifest.json` | Encoding facts, source/output hashes and validation results |

Generated media are intentionally ignored by Git. Send the clean ZIP separately to teammates; cloning the repository does not download the film. Do not distribute the render stage, session token, tooling or raw intermediate segments. The ZIP contains no application database, model, credential or third-party footage.

## Six-shot structure

| Time | Scene |
|---|---|
| 0:00–0:15 | Metallic cooling-valve macro, red warning sweep, pullback into an abstract warehouse |
| 0:15–0:35 | Server/data corridor flyby with electrical sparks and acceleration |
| 0:35–1:15 | Black delivery van in a rainy digital city, overhead plunge and moving chase view |
| 1:15–1:35 | Floating metallic core, cyan ignition and spatial rotation |
| 1:35–1:55 | Expanding algorithmic node network with white/blue pulses |
| 1:55–2:30 | Singapore network map, cyan routing paths and 180-degree orbital camera |

The film uses native Three.js geometry, perspective cameras, physically based metal materials, environment reflections, a wet-floor reflector, bloom, procedural rain, sparks and motion-blur effects. It is a stylized procedural 3D concept film, not photorealistic camera footage or a PPT export.
The requested “8K / RED” language is a visual reference, **not the capture or delivery specification**: actual delivery is 1080p30. No Apple or RED affiliation, endorsement or real-camera capture is claimed.

Original instrumental music and transition sounds are synthesized from oscillators, envelopes and seeded noise. There is no sampled song, TTS, cloned voice or spoken narration.

## Project grounding and limitations

- The map uses the project's 19 facility coordinates: five warehouses and fourteen hospitals. The cyan routes use cached project road paths, not a new online solver run. Buildings, traffic, rain, failures and the timing of route illumination are illustrative.
- The generalized island outline comes from the public-domain [Natural Earth vector dataset](https://github.com/nvkelso/natural-earth-vector), `ne_10m_admin_0_countries.geojson`. The small Singapore-only input records the upstream SHA and scope. It is not a surveyed/current shoreline or a full 3D digital twin. Cached roads retain [OpenStreetMap attribution](https://www.openstreetmap.org/copyright); both sources are credited on screen and in the delivery README.
- Core and network visuals symbolize the handover from observation through analysis, explanation, review, replanning, delivery and audit. They are not screenshots of deployed infrastructure.
- Model advice does not authorize medicine disposition. Human review outcomes remain separate from original advice; preview, adoption and actual delivery are different states. Hospitals are not end-of-day parking locations.
- No live warehouse outage, weather integration, fleet telemetry, millisecond solver performance, clinical validation or new evaluation score is claimed.

This separate 2:30 concept film does **not** replace the course's two five-minute human-presented videos. `submission_ready` remains false; it does not close M6 human-review or genuine-speaker requirements.

## Source and reproduction

Source application snapshot: `182e0d6`. Animation sources: [story](../media/cinematic/story.mjs), [3D film](../media/cinematic/film.mjs), [preview](../media/cinematic/index.html), [Singapore outline](../media/cinematic/assets/singapore-outline.geojson).
Tools: [staging server](../scripts/serve_cinematic.py), [score synthesizer](../scripts/synthesize_cinematic_score.py), [finalizer](../scripts/finalize_cinematic.py).

Use Node.js, Python with NumPy, a full FFmpeg build and a Chromium browser supporting WebGL2 and H.264 WebCodecs. Dependencies are generation tools only, not application dependencies. This render used `three@0.180.0` and `mp4-muxer@5.2.2`, with their MIT licenses copied into the local stage. The muxer is a legacy/deprecated package pinned for this renderer, not a production-library recommendation.

From the repository root, use **fresh** output names:

```bash
npm install --prefix data/processed/cinematic-reproduction/tooling --no-audit --no-fund three@0.180.0 mp4-muxer@5.2.2
.venv/bin/python scripts/serve_cinematic.py --output data/processed/cinematic-reproduction/stage --tools data/processed/cinematic-reproduction/tooling --port 8770
```

Open `http://127.0.0.1:8770` only on the local machine. The preview offers Play/Pause and a timeline; `window.seek(seconds)` positions a frame. Wait for `window.cinematicReady` before capture. In browser developer tools, **await** one ten-second segment at a time:

```javascript
await window.renderMovie({start: 0, end: 10, fps: 30});
```

After it reports `saved`, reload the page and repeat with 10–20, 20–30, …, 140–150. Fifteen authenticated, fixed `part-00.mp4` through `part-14.mp4` slots reject overwrites; the session credential stays local. The server exposes only this render stage, not the repository or application APIs. Do not share it over a network.

Generate the score and assemble the verified film with an actual FFmpeg path:

```bash
.venv/bin/python scripts/synthesize_cinematic_score.py --output data/processed/cinematic-reproduction/score.wav
.venv/bin/python scripts/finalize_cinematic.py --stage data/processed/cinematic-reproduction/stage --score data/processed/cinematic-reproduction/score.wav --ffmpeg /absolute/path/to/ffmpeg --output data/processed/cinematic-reproduction/final
node --test tests/test_cinematic.mjs
.venv/bin/python -m pytest -q tests/test_cinematic_delivery.py tests/test_video_storyboard.py tests/test_submission_package.py
```

Close the task's browser and stop the staging server after rendering. Do not reuse or publish its session token.

## Acceptance record

- Six Node tests passed, zero skips: exact scene timings, English text, camera/render structure and scope guards. Thirty-three Python tests passed across cinematic delivery, existing video storyboards and submission packaging.
- Real-browser preview checks passed at 17 timestamps: English text and safe-frame bounds, moving camera, seek and Play/Pause; no uncaught page errors. WebGL2 and H.264 encoding were available.
- Final encoded frames at 3, 11, 22, 39, 46, 68, 83, 103, 125 and 145 seconds were extracted and visually reviewed across all six scenes. This is sampled visual inspection, not a claim that a human watched every frame.
- Earlier overexposure, camera occlusion and a rectangular placeholder map were corrected before final rendering. An initial whole-film browser save failed; the root cause was not established. The final render used awaited ten-second segments with page reloads, then verified all 15 segments before concatenation.
- Full final video **and** audio decoded without errors; 4,500 frames, 150 seconds, 1080p30 and encoded peak −12.0 dBFS were checked. The clean ZIP passed its internal integrity test.
- SHA checks confirmed the earlier 90-second film and both five-minute films are unchanged. No application API, case database or graph was accessed or modified to make this film; no deployment restart or application-health claim is part of this task.

The source, instructions and tests are committed; media remain local and must be transferred separately.
