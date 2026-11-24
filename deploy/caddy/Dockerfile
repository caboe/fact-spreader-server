# Build the static SPA and the handbook, then serve both behind Caddy.
FROM node:26-alpine AS web
WORKDIR /app
RUN npm install -g pnpm@10.18.3
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# The handbook is built with base `/handbook/` and served from `/srv/handbook`.
FROM node:26-alpine AS handbook
WORKDIR /work
ENV ASTRO_TELEMETRY_DISABLED=1
RUN npm install -g pnpm@10.18.3
COPY site/package.json site/pnpm-lock.yaml ./site/
RUN cd site && pnpm install --frozen-lockfile
COPY handbook/ ./handbook/
COPY site/ ./site/
RUN cd site && pnpm build

FROM caddy:2.10-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /app/build /srv
COPY --from=handbook /work/site/dist /srv/handbook
