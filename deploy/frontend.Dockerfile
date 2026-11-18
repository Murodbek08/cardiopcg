# syntax=docker/dockerfile:1.7
# Build context = repository root (see docker-compose files). Non-root nginx serves the static bundle.
FROM node:22-alpine AS build
ENV CI=1
RUN corepack enable && corepack prepare pnpm@11.12.0 --activate
WORKDIR /app
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY deploy/frontend-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
USER 101
