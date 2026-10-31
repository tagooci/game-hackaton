import { defineConfig } from "vite";

export default defineConfig({
  plugins: [{
    name: "world-no-store",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith("/content/")) res.setHeader("Cache-Control", "no-store");
        next();
      });
    },
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        if (req.url?.startsWith("/content/")) res.setHeader("Cache-Control", "no-store");
        next();
      });
    },
  }],
  optimizeDeps: {
    // Заранее оптимизируем и движок, и GLB-загрузчик вместе.
    // Иначе добавление загрузчика в уже работающую сцену может
    // вызвать пересборку общего кеша зависимостей во время запросов.
    include: ["@babylonjs/core", "@babylonjs/loaders/glTF"],
  },
});
