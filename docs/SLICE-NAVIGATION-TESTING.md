# Slice navigation reliability — research validation

Scope: synthetic or appropriately de-identified medical imaging research only. **MedAxis is not validated for diagnosis.**

## Reproducible behavior
- Each study opens at a centered voxel location `(z, y, x)`, rather than slice zero. The demo first/last slices may contain only noise/background; this is expected of the artificial phantom.
- Case summary `volume_dimensions` stores `[x, y, z]`; backend NIfTI/DICOM volume array shape is `[z, y, x]`. Slider ranges and image requests must use the matching axis.
- The 2D image scales to fit the viewport. Wheel zoom and pointer drag pan operate on the fitted image.
- Slice navigation offers **Previous**, **Center**, **Next**, and a range slider. Manual interaction stops cine so playback will not override the selected index.
- Research intensity statistics update after a 280 ms debounce for the selected plane/index. Cine deliberately defers repeated measurement requests until paused.
- MPR coordinates use the shared `{z, y, x}` position. Requests are canceled logically on UI updates, and include the 2D window width/level for consistent presentation.
- Actual pixel data are rendered by FastAPI. Errors should show a visible in-viewport message, not a silent broken image.

## Manual acceptance sequence
1. Start Python 3.11 backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
2. Run `npm run typecheck` and `npm run build` in the frontend.
3. Open MedAxis, click **Open Demo Case**, and verify it opens near axial slice **48 / 96**, not slice 1.
4. Drag the axial slice slider from 48 to 1, 30 and 80. The displayed slice number and underlying image should change. Slice 1 can legitimately be noisy/background in this phantom.
5. Click **Center**, **Next**, **Previous** and verify changes.
6. Switch to coronal and sagittal; the range should be **1–160** for the 160×160×96 synthetic phantom and the image should update.
7. Move the slider and wait approximately one second; the source-derived research measurements should update for the chosen plane.
8. Start cine playback and change the slider manually. Cine should stop immediately.
9. Open 4-Panel MPR, click a crosshair position, and verify the coordinates and orthogonal images update without displaying stale responses. Changing the 2D window should update MPR images.
10. Test the image endpoint directly for first/center/last of all three planes; verify HTTP 200 PNG and different pixel content for more than one position. Run the new backend pytest test.
11. Deliberately stop FastAPI and verify the app reports the disconnect; restart and reconnect.

## Research and clinical limitations
- A pretty grayscale rendering and a `QC PASS` status do not prove that image orientation, VOI LUT, modality rescale or geometry are correct for all scanner vendors.
- Full-range statistics include all pixels on a plane, **not an ROI lesion or organ measurement**.
- The synthetic phantom is not representative of human tissue.
- Patient diagnosis requires task-appropriate independent accuracy studies, secure access, validation, regulatory review and clinician oversight. This feature is for research only.
