FROM node:20-slim

WORKDIR /app

# Copy package files first for better layer caching
COPY package*.json ./
RUN npm install

# Copy source code
COPY . .

# Expose Vite dev server port
EXPOSE 5174

# Run development server with host binding and HMR
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5174"]
