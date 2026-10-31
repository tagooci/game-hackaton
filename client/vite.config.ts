import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [{
    name: 'content-no-store',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith('/content/')) res.setHeader('Cache-Control', 'no-store');
        next();
      });
    },
  }],
  server: {
    host: '0.0.0.0',
    port: 5179,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
});
