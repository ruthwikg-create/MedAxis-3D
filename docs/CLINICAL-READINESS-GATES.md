# MedAxis-3D research-to-clinical readiness gate

## Present classification
Research/educational prototype; not validated for clinical diagnosis or treatment decisions.

## Current evidence
Synthetic NIfTI study renders in the user-reported 2D/MPR views; backend reported ONLINE; source-derived plane statistics and QC were displayed. These are smoke-test observations, not verification of image calibration or clinical accuracy.

## Misleading labels corrected
- Renamed `2D Diagnostic` workspace to `2D Research Viewer` (including default and keyboard navigation).
- Replaced unconditional `Audit trail enabled` label with `Audit events: research logs only`. Proper immutable access/audit enforcement has not been demonstrated.
- Changed `Source provenance tracked` to `research metadata` until independently verified.
- Changed QC status label to `Header / geometry QC`. A PASS does not mean medically safe.
- Clarified that AI outputs are not clinically validated and measurements are experimental.

## Mandatory gates before a clinician could rely on this application
- Define a specific intended clinical use, user population and supported modality/scanners.
- DICOM conformance evaluation, multi-frame and transfer syntax testing, UIDs/series/geometry/slice order audits.
- Pixel intensity and Hounsfield-unit testing against known reference datasets and independent radiology software; VOI LUT and presentation-state consistency.
- Measurement uncertainty, interpolation and resampling accuracy testing, reference phantom testing across modalities and voxel spacing.
- Independent retrospective/prospective clinical studies of task-specific inference, sensitivity/specificity, calibration, bias, domain shift and error handling.
- Secure institutional authentication and patient/study-level authorization, data retention and privacy controls, cryptographic transport and durable tamper-evident audit logs.
- Traceable requirements, software risk management, usability, cybersecurity threat modeling, monitoring, and applicable jurisdictional medical-device regulatory clearance/approval.

## Browser smoke test after updating branch
1. `npm run typecheck` and `npm run build` pass in `frontend`.
2. Both backend and frontend start; `/api/health` says `ONLINE`.
3. Create/open a synthetic case, verify a readable image in axial/sagittal/coronal and synchronized MPR.
4. Verify workspace selection says `2D Research Viewer`, not `2D Diagnostic`.
5. Verify displayed QC says `Header / geometry QC`, and audit description says `research logs only`.
6. Verify measurement outputs are accompanied by a research-use warning.
7. Test invalid/missing data and backend outage; system should explain missing features, not make up clinical findings.
8. Do not use identifiable patient studies.

Completing these UI/build checks will not satisfy clinical-readiness requirements.
