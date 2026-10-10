// Third-party notices for the web app: every production dependency in package-lock.json with its
// licence, written to dist/licenses.json (shown on the About page next to the server's own list).
import { readFileSync, writeFileSync } from 'node:fs';

const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url)));
const packages = Object.entries(lock.packages)
  .filter(([path, p]) => path.startsWith('node_modules/') && !p.dev && !p.devOptional)
  .map(([path, p]) => ({
    name: path.slice(path.lastIndexOf('node_modules/') + 'node_modules/'.length),
    version: p.version,
    license: p.license ?? 'see package',
  }))
  .sort((a, b) => a.name.localeCompare(b.name));
writeFileSync(new URL('../dist/licenses.json', import.meta.url), JSON.stringify(packages));
console.log(`licenses.json: ${packages.length} packages`);
