/**
 * Validate every Mermaid diagram in the repository.
 *
 * Parses each ```mermaid block with Mermaid's own parser under jsdom. This
 * catches the syntax errors that matter — a diagram that fails to parse renders
 * on GitHub as a raw code block, and nobody notices for months.
 *
 * Deliberately does NOT use @mermaid-js/mermaid-cli: that needs a full Chromium
 * download to render an SVG we then throw away. This is the same parser, a few
 * seconds instead of a few minutes, and it runs on a machine with no browser.
 *
 *   npm --prefix scripts/mermaid install   # once
 *   node scripts/mermaid/check_mermaid.mjs
 */
import { JSDOM } from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';

const SKIP = new Set(['node_modules', 'venv', '.venv', 'dist', '.git', '__pycache__']);

function markdownFiles(dir, acc = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) markdownFiles(full, acc);
    else if (entry.name.endsWith('.md')) acc.push(full);
  }
  return acc;
}

const dom = new JSDOM('<!doctype html><html><body></body></html>');
global.window = dom.window;
global.document = dom.window.document;
global.navigator = dom.window.navigator;

const mermaid = (await import('mermaid')).default;
mermaid.initialize({ startOnLoad: false, securityLevel: 'loose' });

const root = process.argv[2] ?? '.';
let total = 0;
let failed = 0;
const inActions = Boolean(process.env.GITHUB_ACTIONS);

for (const file of markdownFiles(root).sort()) {
  const text = fs.readFileSync(file, 'utf8');
  const blocks = [...text.matchAll(/```mermaid\n([\s\S]*?)```/g)].map((m) => m[1]);
  for (let i = 0; i < blocks.length; i++) {
    total++;
    try {
      await mermaid.parse(blocks[i]);
    } catch (err) {
      failed++;
      const msg = String(err.message).split('\n').slice(0, 5).join(' ');
      const line = `${file} (diagram ${i + 1}): ${msg}`;
      console.log(inActions ? `::error file=${file}::${msg}` : `FAIL  ${line}`);
      // A semicolon in a sequence-diagram message or note is the usual cause:
      // Mermaid treats it as a statement separator and truncates the text.
    }
  }
}

console.log(`\n${total} Mermaid diagrams parsed, ${failed} failed.`);
process.exit(failed ? 1 : 0);
