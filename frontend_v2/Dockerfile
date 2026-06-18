FROM node:20-slim AS dev
WORKDIR /app

# Copy package files first for better layer caching
COPY package*.json ./
COPY scripts/enforce-npm.cjs ./scripts/enforce-npm.cjs
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
# Copy built assets to Nginx
COPY --from=builder /app/dist /usr/share/nginx/html
# (Optional) Copy custom nginx config if needed
# COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
