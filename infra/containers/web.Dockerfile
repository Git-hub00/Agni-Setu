# syntax=docker/dockerfile:1.7
# Agni Setu web image: builds the SPA with the pinned pnpm, serves it with nginx as an unprivileged
# user on port 8080 and proxies /api/ to the api service. Bases pinned by digest
# (infra/images.lock.json "node-base", "nginx-base").
# Build context: web/  (docker build -f infra/containers/web.Dockerfile web/)

FROM node:24-alpine@sha256:50c8e8ca1d27439048670df5883f32d57cf81cff6233222c893fd0d9884cbd81 AS build

WORKDIR /app
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable && corepack prepare pnpm@12.3.4 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
# Source maps are "hidden" build artefacts (vite.config.ts); they never enter the served image.
RUN pnpm build && find dist -type f -name '*.map' -delete

# ---------------------------------------------------------------------------------------------
FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de AS runtime

# Apply the distribution's security updates on top of the pinned base (B18 scan found fixed
# openssl / util-linux / libxml2 / nghttp2 advisories newer than the base digest), then run nginx
# as the unprivileged `nginx` user: listen on 8080, write pid/cache to writable paths.
RUN apk --no-cache upgrade \
    && rm /etc/nginx/conf.d/default.conf \
    && sed -i -E 's#^pid\s+.*;#pid /tmp/nginx.pid;#' /etc/nginx/nginx.conf \
    && sed -i -E 's#^user\s+.*;##' /etc/nginx/nginx.conf \
    && grep -q '^pid /tmp/nginx.pid;' /etc/nginx/nginx.conf \
    && mkdir -p /var/cache/nginx /tmp/nginx \
    && chown -R nginx:nginx /var/cache/nginx /tmp/nginx /var/log/nginx /etc/nginx/conf.d

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/security-headers.conf /etc/nginx/agni/security-headers.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
