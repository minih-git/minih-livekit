
import { defineConfig } from '@rsbuild/core';
import { pluginReact } from '@rsbuild/plugin-react';

export default defineConfig({
  plugins: [pluginReact()],
  html: {
    template: './src/index.html',
  },
  source: {
    entry: {
      index: './src/index.tsx',
    },
  },
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: 'http://121.5.28.27:8081',
        changeOrigin: true,
      },
    },
  },
});
