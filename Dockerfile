ARG NODE_IMAGE=node:24.15.0-bookworm-slim@sha256:4e6b70dd6cbfc88c8157ba19aa3d9f9cce6ba4703576d55459e45efcbc9c5f5d
ARG PYTHON_IMAGE=python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
FROM ${NODE_IMAGE} AS frontend
WORKDIR /frontend
RUN npm install --global pnpm@12.4.1
COPY frontend-vue/package.json frontend-vue/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend-vue/src ./src
COPY frontend-vue/index.html frontend-vue/vite.config.js ./
ENV VITE_API_BASE=same-origin
RUN pnpm build

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/mpl LOKY_MAX_CPU_COUNT=1
COPY requirements-runtime.lock.txt ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.lock.txt && python -m pip check
ENV ML_MODEL_DIR=/app/models FRONTEND_DIST=/app/frontend-dist CORS_ORIGINS="" DATABASE_URL=/runtime/audit/dispatch.sqlite3 CASE_RUNS_FILE=/runtime/audit/runs.jsonl
COPY src ./src
COPY scripts/train_m4_models.py scripts/bootstrap_demo.py scripts/runtime_snapshot.py scripts/check_case_graph.py ./scripts/
COPY data/optimisation ./data/optimisation
COPY data/ml/cold-chain-silent-failure/shipment-sensor-dataset.csv ./data/ml/cold-chain-silent-failure/
COPY data/ml/electricsheepafrica__vaccine-cold-chain/*.csv ./data/ml/electricsheepafrica__vaccine-cold-chain/
# Regenerate trusted models INSIDE the serving environment; never COPY host pickle artifacts.
RUN python scripts/train_m4_models.py --output /app/models
COPY --from=frontend /frontend/dist ./frontend-dist
RUN chmod -R a+rX /app && groupadd --gid 10001 demo && useradd --uid 10001 --gid 10001 --no-create-home demo && mkdir -p /runtime/audit && chown -R 10001:10001 /runtime
USER 10001:10001
RUN PYTHONPATH=/app/src python -c "from api.main import app; from ml.runtime import model_info; assert all(model_info(t)['status']=='ready' for t in ['risk','cause']); assert any(r.path=='/api/ready' for r in app.routes)"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "--app-dir", "src", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
