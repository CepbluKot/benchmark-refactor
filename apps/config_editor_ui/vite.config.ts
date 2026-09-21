import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Сборка рассчитана на закрытый контур: относительные пути к ассетам,
// никаких внешних CDN, шрифты — системные.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false,
    target: 'es2020',
  },
});
