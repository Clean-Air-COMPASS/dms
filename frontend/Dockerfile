



FROM node:24.22.0-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS build

WORKDIR /app


COPY frontend/package.json frontend/package-lock.json ./

RUN npm install --include=optional --no-audit --no-fund \
  && ROLLUP_VERSION=$(node -p "require('./package-lock.json').packages['node_modules/rollup'].version") \
  && npm install --no-save @rollup/rollup-linux-x64-gnu@${ROLLUP_VERSION}


COPY frontend/ .

ARG COMPASSAQ_BUILD_SHA
RUN COMPASSAQ_BUILD_TIME_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ) npm run build


# The slim image includes the core static/proxy modules without unused image/XML modules.
FROM nginx:1.30.6-alpine-slim@sha256:3028fc1419f99b95c1c69f844bbaf49dc1b881750c51b497fc721ac4f02a14e6 AS runtime

COPY frontend/nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --chmod=755 frontend/nginx/healthcheck.sh /usr/local/bin/frontend-healthcheck
COPY --from=build /app/dist /usr/share/nginx/html

HEALTHCHECK --interval=5s --timeout=5s --start-period=5s --retries=3 \
  CMD ["/usr/local/bin/frontend-healthcheck"]

EXPOSE 80
