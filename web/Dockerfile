# The fly ships itself: connectome in, static site out.
#
# Build context is the repository root, not `web/` — the compiled brain
# comes from the Python half, so the image needs both.
#
#   docker build -f web/Dockerfile -t fruit-fly .

# ---------------------------------------------------------------- brain
FROM python:3.12-slim AS brain
WORKDIR /src
# numpy only. The connectome compiler does not need cairo or GTK, and
# pulling the display stack in here would double the stage for nothing.
RUN pip install --no-cache-dir numpy
COPY pyproject.toml ./
COPY fruitfly ./fruitfly
# `data/` is optional: if CI restored the cache it is here and the fetch
# is skipped, otherwise this downloads ~50 MB of FlyWire tables.
COPY dat[a] ./data
RUN python -m fruitfly prepare \
 && python -m fruitfly export-web --no-parity \
 && gzip -9 -k web/public/brain/brain.bin \
 && ls -la web/public/brain

# ----------------------------------------------------------------- site
FROM node:22-slim AS site
WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
COPY --from=brain /src/web/public/brain ./public/brain
RUN npm run typecheck && npm run build \
 && cp -r public/brain dist/brain

# ----------------------------------------------------------------- serve
FROM nginx:alpine
COPY web/nginx.conf /etc/nginx/nginx.conf
COPY --from=site /app/dist /usr/share/nginx/html
# Cloud Run's contract. nginx.conf listens on 8080 to match.
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://127.0.0.1:8080/ping || exit 1
