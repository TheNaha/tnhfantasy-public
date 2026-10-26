FROM node:24-slim AS dev
WORKDIR /app

# Copy package files first for better layer caching
COPY package*.json ./
COPY scripts/enforce-npm.cjs ./scripts/enforce-npm.cjs
RUN apt-get update && apt-get install -y wget curl && rm -rf /var/lib/apt/lists/*
RUN npm ci

# Copy source code
COPY . .

# Expose Vite dev server port
EXPOSE 5174

# Run development server with host binding and HMR
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5174"]

FROM dev AS builder
# Build static files
RUN npm run build

FROM nginx:alpine AS prod
# Install wget for healthcheck support
RUN apk add --no-cache wget

# Run as a non-root user.
#
# Every other service in the stack is pinned to uid/gid 1000 — the backend, all
# five providers — and this one was the only exception, running as root. It is
# also the ONLY service Traefik routes to, and its nginx terminates the public
# entrypoint and proxies /api/ and /socket.io/ to the backend. Root RCE in the
# process facing the internet is a full-stack compromise, so this is the one
# container where the default mattered most.
#
# nginx needs writable pid/temp paths as a non-root user. `pid` cannot live in
# conf.d (main-context only), so it is in the main nginx.conf we supply here;
# the temp paths are set in both files because they are the http-level defaults
# and the vhost narrowing. 5174 is already an unprivileged port, so the listener
# itself needs no capability.
RUN addgroup -g 1000 -S app && adduser -u 1000 -S -G app app \
 && mkdir -p /tmp/nginx-client-body /tmp/nginx-proxy /tmp/nginx-fastcgi \
             /tmp/nginx-uwsgi /tmp/nginx-scgi \
 && chown -R app:app /usr/share/nginx/html /var/cache/nginx /tmp/nginx-*

# Copy built assets to Nginx
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-main.conf /etc/nginx/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 5174
USER app
CMD ["nginx", "-g", "daemon off;"]
