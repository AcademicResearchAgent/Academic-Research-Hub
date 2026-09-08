// Lightweight syntax/compile check; does not replace the complete application build.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, '.build/source-check/package.json'));
const { compile } = require('svelte/compiler');
for (const file of [
  'src/routes/auth/+page.svelte', 'src/routes/+layout.svelte',
  'src/lib/components/OnBoarding.svelte', 'src/lib/components/channel/Channel.svelte'
]) {
  const filename = path.join(root, 'reference/open-webui', file);
  const result = compile(fs.readFileSync(filename, 'utf8'), { filename, generate: 'client' });
  console.log(`${file}: compile OK (${result.warnings.length} compiler warnings)`);
}
