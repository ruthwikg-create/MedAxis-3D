# CT → MRI Research Synthesis

MedAxis exposes CT → MRI synthesis only when a compatible, externally trained checkpoint is installed.

## Current supported contract

- Input: 3D CT volume
- Output: 3D synthetic MRI-like volume
- Runtime: PyTorch TorchScript
- Default path: `backend/models/cross_modality/ct_to_mri.ts`
- Environment override: `CROSS_MODALITY_MODEL_PATH`
- Status: research-only
- Synthetic output is never treated as acquired MRI.

## Recommended open research implementation

MICV-Yonsei CT2MRI:
https://github.com/MICV-yonsei/CT2MRI

This is a MICCAI 2024 research implementation for slice-consistent 3D volumetric **brain CT-to-MRI** translation. It provides PyTorch source code and training/testing pipelines, but the public repository does not provide a drop-in MedAxis TorchScript checkpoint.

## Do not do this

Do not rename an arbitrary `.pt`, `.pth`, Stable Diffusion, segmentation, or CT generative checkpoint to `ct_to_mri.ts`. File extension changes do not make model architecture, preprocessing, tensor shapes, or weights compatible.

Do not label synthetic MRI as acquired MRI and do not report clinical diagnostic accuracy without independent validation.

## Installation contract

After obtaining or training a compatible brain CT→MRI checkpoint:

1. Convert/export the exact model to TorchScript with an input/output contract compatible with `backend/app/services/synthesis.py`.
2. Place it at:
   `backend/models/cross_modality/ct_to_mri.ts`
   or set `CROSS_MODALITY_MODEL_PATH`.
3. Verify:
   `curl http://127.0.0.1:8000/api/advanced/synthesis/status`
4. Confirm the response says `MODEL READY`.
5. Run synthesis only on compatible brain CT research data.

The current MedAxis backend intentionally refuses to claim readiness when this checkpoint is absent.
