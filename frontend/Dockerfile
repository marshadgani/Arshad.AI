# Multi-stage build.
# Local dev (compose uses target=dev): hot-reload Vite server bound to 0.0.0.0:3000.
# Production (target=prod): static assets served by nginx as a non-root user.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

FROM node:20-alpine AS dev
WORKDIR /app
RUN addgroup -S app && adduser -S app -G app
COPY --from=deps /app/node_modules ./node_modules
COPY --chown=app:app . .
USER app
EXPOSE 3000
CMD ["npm", "start", "--", "--host", "0.0.0.0"]

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS prod
RUN addgroup -S app && adduser -S app -G app \
    && mkdir -p /tmp/nginx-body /tmp/nginx-proxy /tmp/nginx-fastcgi /tmp/nginx-uwsgi /tmp/nginx-scgi \
    && chown -R app:app /var/cache/nginx /var/log/nginx /tmp/nginx-* /usr/share/nginx/html
# Store the config as a template; BACKEND_URL is substituted at startup.
COPY nginx.conf /etc/nginx/nginx.conf.template
COPY --from=build --chown=app:app /app/dist /usr/share/nginx/html
USER app
EXPOSE 8080
# Only substitute ${BACKEND_URL} — leave nginx variables ($uri, $http_host, …) untouched.
CMD ["/bin/sh", "-c", "envsubst '${BACKEND_URL}' < /etc/nginx/nginx.conf.template > /tmp/nginx-runtime.conf && nginx -c /tmp/nginx-runtime.conf -g 'daemon off;'"]
