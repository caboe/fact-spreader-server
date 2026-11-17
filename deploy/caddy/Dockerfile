# Build the static SPA, then serve it behind Caddy together with the API and SSE.
FROM node:26-alpine AS web
WORKDIR /app
RUN npm install -g pnpm@10.18.3
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM caddy:2.10-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=web /app/build /srv
