# MedAxis 3D — Infrastructure Verification

## Development branch

The infrastructure implementation is developed on `feature/medaxis-ai-infrastructure` before merge to `main`.

## Verification contract

Every change should pass:

- Python source compilation.
- Backend pytest suite.
- Frontend TypeScript typecheck.
- Frontend production build.
- Runtime health/readiness endpoints.
- Model readiness checks that never report missing artifacts as ready.

## Runtime configuration

Copy `.env.example` to `.env` and configure only the services required for the deployment.

### Local research mode

The default local mode uses SQLite and filesystem object storage. Authentication is disabled unless `AUTH_REQUIRED=true`.

### PostgreSQL

Set:

`DATABASE_URL=postgresql+psycopg://medaxis:<password>@<host>:5432/medaxis`

The application uses SQLAlchemy and creates its current schema at startup. Production deployments should add controlled migrations before schema evolution.

### S3-compatible storage

Set `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY`. MinIO is supported through the same S3-compatible interface.

### Authentication

For an authenticated deployment:

`AUTH_REQUIRED=true`

and provide a random `JWT_SECRET` of at least 32 characters. Do not commit secrets.

### GPU

The backend reports `cuda` only when the installed PyTorch runtime can access CUDA. Otherwise it explicitly reports `cpu`; it never claims GPU acceleration merely because a GPU may exist in the host.

### MONAI models

Model bundles and weights are intentionally excluded from Git. Use the Model Manager/download endpoint or the supplied model download scripts. A model is reported as ready only when both a supported inference configuration and weight artifact are present and the MONAI/PyTorch runtime is importable.

### Clinical status

MedAxis 3D is a research/educational workstation. Software capability, publisher benchmarks, or automated tests do not constitute clinical validation or regulatory clearance.
