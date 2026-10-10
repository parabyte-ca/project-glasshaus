// Give each build its own service-worker cache name, so a new release activates a new worker that
// deletes the previous cache (otherwise hashed /assets/ files from old releases pile up).
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';

const dist = new URL('../dist/', import.meta.url);
const index = readFileSync(new URL('index.html', dist));
const stamp = createHash('sha256').update(index).digest('hex').slice(0, 12);
const sw = new URL('sw.js', dist);
const source = readFileSync(sw, 'utf8');
if (!source.includes("'glasshaus-shell-v2'")) throw new Error('sw.js cache name not found');
writeFileSync(sw, source.replace("'glasshaus-shell-v2'", `'glasshaus-shell-${stamp}'`));
console.log(`sw.js: cache glasshaus-shell-${stamp}`);
