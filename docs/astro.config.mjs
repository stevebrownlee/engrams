import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://engrams.sh',
  outDir: './dist',
  vite: {
    define: {
      __APP_VERSION__: JSON.stringify(process.env.APP_VERSION || '1.1.2'),
    },
  },
});
