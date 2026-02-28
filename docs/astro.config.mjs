import { defineConfig } from 'astro/config';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const pyproject = readFileSync(resolve(__dirname, '..', 'pyproject.toml'), 'utf-8');
const versionMatch = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
const version = process.env.APP_VERSION || (versionMatch ? versionMatch[1] : '0.0.0');

export default defineConfig({
  site: 'https://engrams.sh',
  outDir: './dist',
  vite: {
    define: {
      __APP_VERSION__: JSON.stringify(version),
    },
  },
});
