import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '0.0.0.0',
    port: 5179,
    strictPort: true,
    proxy: {
      '/lab': { target: 'http://127.0.0.1:8011', ws: true },
    },
  },
});
