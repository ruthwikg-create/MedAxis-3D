# MedAxis-3D unified integration — Phase 1

This branch begins the **MedAxis-3D** integration of research capabilities from WebPACS-3D and RadAssist-3D. It is not a full merge of every source file.

## Architecture decisions

- Preserve MedAxis 4.1.1 Next.js 16/React 19 frontend and FastAPI image-analysis backend.
- Preserve MedAxis's existing segmentation, source-derived measurements, AI adapters, DICOM/NIfTI ingestion, QC and reporting services.
- Do not paste WebPACS's Next.js 14/React 18/Clerk middleware, Cornerstone dependencies or Supabase backend directly into MedAxis. Identity and deployment stacks are incompatible and would risk bypassing authorization.
- The first independently usable integration is a client-side **Experiment & Provenance Lab** at `/research`, linked from the MedAxis workstation.
- No patient data, imaging files or experiments are sent to MedAxis's server by this new component. An exported manifest may still include sensitive text if the user types any; use only synthetic or de-identified data.

## Implemented workflow

1. Start existing MedAxis backend and frontend using README instructions.
2. Open the main workstation, optionally create a synthetic demo case with its existing tools.
3. Select the floating **Research Lab** link.
4. Record hypothesis, protocol, dataset alias and exact tested Git commit.
5. Enter independently obtained measurements, noting metric, unit, method and uncertainty.
6. Export JSON (`medaxis-experiment-v1`) or CSV; refresh to verify session-only storage.
7. Re-import JSON and verify no values were lost.

The JSON manifest explicitly states `imagingAutomaticallyMeasured: false`, `containsImages: false`, and `source: researcher-entered`. These values are not calculated from images by this UI.

## Scientific acceptance tests (manual until browser automation is added)

- [ ] `cd frontend && npm ci && npm run typecheck && npm run build` passes.
- [ ] `cd backend && python -m pytest -q` passes with installed dependencies.
- [ ] Main app displays Research Lab navigation; clicking opens `/research`.
- [ ] Add, remove and export measurements; arithmetic mean matches external calculation.
- [ ] Enter a comma and quote in the observation field; CSV imports into Python correctly.
- [ ] Export JSON, reload, import JSON, and verify fields and counts match.
- [ ] Invalid JSON and malformed entries are rejected without changing the experiment.
- [ ] The browser's Network tab shows no new POST for typing and exporting experiment entries.
- [ ] Sign-in/authorization and existing demo/AI/quantitative workflows have not regressed.
- [ ] Confirm repository `data/medaxis-dev.db` contains no identifiable medical data; remove data and rotate affected credentials if findings require it.

## Next development phases (not in this PR)

1. Build one durable study identity and authorization design across frontend and backend; prefer server-side enforcement and remove token-in-localStorage risk.
2. Implement validated DICOMweb/QIDO/WADO adapters using authenticated server-side allowlists and study permissions.
3. Adapt selected WebPACS Cornerstone3D tools inside the MedAxis frontend, resolving React and bundler compatibility and avoiding redundant rendering engines.
4. Expand MedAxis source-derived quantitative imaging with verified ROI pixel statistics and calibration reports.
5. Integrate RadAssist algorithm benchmarking only where existing MedAxis metrics or adapters do not already cover it.
6. Design controlled, versioned experiments and datasets, immutable audit, secure persistence and reproducible model manifests.
7. Perform dataset-reference, imaging-accuracy, robustness, security and human-factors verification before any claim of clinical or diagnostic capability.

This is a research-only application. Clinical use requires formal validation, security/privacy controls and applicable regulatory review.
