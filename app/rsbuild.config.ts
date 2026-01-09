
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
  },
});
