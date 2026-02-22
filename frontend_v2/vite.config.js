import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'xml'],
      include: ['src/**/*.js', 'src/**/*.jsx'],
      exclude: ['src/test/**', 'src/main.jsx'],
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    // HMR configuration for Docker
    watch: {
      usePolling: true,  // Required for Docker volume mounts
      interval: 1000,
    },
    hmr: {
      host: 'localhost',  // HMR connects from browser to host
      port: 5174,
    },
    proxy: {
      '/api': {
        // Use VITE_PROXY_TARGET for server-side proxy (Docker hostname)
        // Falls back to VITE_API_URL then localhost
        target: process.env.VITE_PROXY_TARGET || process.env.VITE_API_URL || 'http://localhost:8002',
        changeOrigin: true,
        secure: false,
        ws: true,
      },
      '/socket.io': {
        target: process.env.VITE_PROXY_TARGET || process.env.VITE_API_URL || 'http://localhost:8002',
        changeOrigin: true,
        secure: false,
        ws: true,
      }
    }
  },
  build: {
    // Chunk size warning limit
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        // Manual chunks for better caching
        // Vendor code changes less than app code, so separate bundles = better cache hits
        manualChunks: {
          // React core
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // React Query (data layer)
          'vendor-query': ['@tanstack/react-query'],
          // Animation library
          'vendor-motion': ['framer-motion'],
          // Visualization/Charts
          'vendor-viz': ['react-virtuoso', 'react-window', 'react-hot-toast'],
          // Blurhash for progressive images
          'vendor-blurhash': ['blurhash', 'react-blurhash'],
          // Lucide icons (tree-shakeable, but still sizeable)
          'vendor-icons': ['lucide-react'],
        }
      }
    }
  }
})

