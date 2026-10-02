# MedAxis 3D 4.1.1 — Windows quick start

Use the repository scripts instead of manually guessing folder paths.

From `medaxis-audit`:

```cmd
scripts\INSTALL_WINDOWS.cmd
```

This creates `backend\.venv`, installs Python dependencies, installs npm dependencies, runs the frontend typecheck/build, and runs the backend tests.

Start the application:

```cmd
scripts\START_WINDOWS.cmd
```

The script opens separate backend and frontend terminals and opens `http://localhost:3000`.

Verify again later:

```cmd
scripts\VERIFY_WINDOWS.cmd
```

Download MONAI research bundles only when needed:

```cmd
scripts\DOWNLOAD_MODELS_WINDOWS.cmd
```

Do **not** type `package.json` at a command prompt. To inspect it, use:

```cmd
type frontend\package.json
```

## Production configuration

Copy `.env.example` to `.env` and configure:

- `AUTH_REQUIRED=true`
- a random `JWT_SECRET` with at least 32 characters
- `DATABASE_URL` pointing to PostgreSQL
- S3/MinIO variables for object storage
- a validated `CROSS_MODALITY_MODEL_PATH` for CT→MRI synthesis

Clinical validation is not created by configuration. The application contains a validation workflow for independently generated evidence.
