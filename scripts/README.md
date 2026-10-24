# Scripts index

Helper scripts for building, evaluating, recording and packaging the project.
Runtime code lives in `src/`; tests live in `tests/`.

Most scripts are run from the repository root with the evaluation environment:

```bash
.venv/bin/python scripts/<name>.py --help
```

## Environment, data and deployment

| Script | Purpose |
|---|---|
| `configure_demo.py` | Generate local demo env files (never overwrites) |
| `bootstrap_demo.py` | Seed a fresh demonstration instance |
| `init_dispatch_db.py` | Create the dispatch SQLite schema |
| `download_data.py` · `export_demo_data.py` | Fetch inputs / export demo fixtures |
| `build_singapore_network.py` · `export_singapore_routes.py` | Build the Singapore road network and route cache |
| `sync_knowledge_graph.py` | Replay the case outbox into Neo4j |
| `check_reproduction.py` | Verify pinned versions and input hashes |
| `verify_deployment.py` | Check a running deployment is ready |

## Experiments and evaluation

| Script | Purpose |
|---|---|
| `evaluate_engine.py` · `evaluate_m3_formal.py` | Rule-engine agreement and formal M3 scores |
| `evaluate_m4.py` · `train_m4_models.py` · `train_risk_model.py` · `train_risk_full.py` · `train_root_cause.py` | Risk and cause models, calibration and SHAP |
| `evaluate_m5_formal.py` · `run_routing_baselines.py` · `plot_disruption_comparison.py` | Routing benchmarks and comparison figures |
| `evaluate_m6_independent.py` · `summarize_m6_review.py` · `finalize_m6_review.py` · `check_m6_annotation.py` | M6 human-review preparation, scoring and closeout |
| `evaluate_qa.py` · `audit_datasets.py` · `audit_cause_learnability.py` | QA evaluation and dataset audits |
| `generate_event_dataset.py` · `event_v2_data.py` · `evaluate_event_baselines.py` · `evaluate_event_gate.py` · `evaluate_event_v2.py` · `verify_event_dataset.py` | Event-level simulation and temporal models |
| `check_case_graph.py` · `check_provenance.py` · `verify_graph_recovery.py` | Graph, provenance and recovery checks |

## Report and presentation

| Script | Purpose |
|---|---|
| `build_final_report.py` | Build the report DOCX and merge the proposal PDF |
| `build_report_figures.py` · `run_report_case_study.py` | Report figures and case-study evidence |
| `build_final_presentation.mjs` · `build_presentation_final.py` | Final and generated presentation decks |
| `build_proposal_docx.py` · `build_speech_docx.py` · `build_qa_docx.py` · `docx_kit.py` | Proposal, script and Q&A DOCX generation |
| `deck_theme.py` · `check_deck_theme.py` · `check_decks.py` · `check_deck_facts.py` · `check_deck_geometry.py` · `check_ppt_text_budget.py` | Deck styling and consistency checks |
| `check_speech_docx.py` · `check_speech_matches_deck.py` · `diff_proposal_vs_docx.py` | Speech/deck consistency and DOCX diffs |
| `dump_pptx_text.py` · `extract_pdf_text.py` | Text extraction helpers |
| `fix_deck_facts.py` · `set_group_number.py` · `restore_screenshot.py` | Deck maintenance |
| `export-slides.ps1` · `export-slides.cmd` | Export slides to images |

## Video production

| Script | Purpose |
|---|---|
| `build_keynote_promo.py` · `build_keynote_system.py` | Render the two keynote-style videos |
| `build_demo_videos.py` · `record_business_video.cjs` · `serve_video_demo.py` | Record the live demonstration |
| `mix_voiceover.py` | Mix recorded narration onto a video |
| `render_explainer.mjs` · `finalize_explainer.py` · `synthesize_explainer_score.py` | Code-drawn explainer |
| `finalize_cinematic.py` · `serve_cinematic.py` · `synthesize_cinematic_score.py` | Six-scene concept film |
| `prepare_ui_shot.py` | Prepare clean UI screenshots |

## Acceptance and packaging

| Script | Purpose |
|---|---|
| `browser_*.cjs` | Playwright acceptance flows (demo, review, M2/M4/M6, v2) |
| `run_demo_acceptance.py` | End-to-end acceptance runner |
| `check_deployed_v2_shadow.py` · `check_v2_shadow_runtime.py` · `prepare_v2_shadow_deployment.py` · `package_event_v2_shadow.py` | v2 shadow deployment checks |
| `check-frontend-i18n.mjs` · `check-frontend-sfc.mjs` · `test-*.mjs` · `dev-check.ps1` | Frontend checks |
| `package_submission.py` | Assemble the course submission zip (video files or YouTube links) |
| `m6_review_form.html` · `m6_review_form_selftest.mjs` | Offline M6 review form and self-test |

## Utilities

`runtime_snapshot.py`, `fetch_map_tiles.mjs`, `predict_qa_intents.mjs` and the
`check_*.py` helpers are small utilities used by the scripts above.
