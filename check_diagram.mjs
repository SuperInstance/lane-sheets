#!/usr/bin/env node
// Correctness harness for the sheet visualiser (docs/js/diagram.js).
//
//   node check_diagram.mjs
//
// Runs sheetToSvg over every positive fixture in docs/fixtures/ and
// asserts, per fixture:
//   (a) it does not throw;
//   (b) every cell id in the sheet appears in the SVG;
//   (c) the number of arrow paths (paths with class "pipe") equals
//       the total declared-input count of the sheet, computed
//       independently here straight from the fixture JSON -- never
//       from the diagram module's own bookkeeping;
//   (d) the SVG is well-formed XML, checked with the simple stack
//       checker below (tag nesting + single root + no stray "<" in
//       text). No XML parser is installed in this tree, and none was
//       added: the stack checker is the stated method, and it is
//       strict about the failure modes a string generator can
//       actually produce (unbalanced/mis-nested tags, unescaped
//       text, multiple roots).
//
// Prints one line per fixture and a summary. Exit 0 only if all pass.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { sheetToSvg } from "./docs/js/diagram.js";

const ROOT = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(ROOT, "docs", "fixtures");

// ------------------------------------------------------------------
// (d) Minimal strict XML well-formedness: a stack checker.
// ------------------------------------------------------------------
function checkXmlWellFormed(xml) {
  const stack = [];
  let roots = 0;
  let i = 0;
  const fail = (msg) => {
    throw new Error(`XML: ${msg} (at offset ${i})`);
  };
  while (i < xml.length) {
    const lt = xml.indexOf("<", i);
    if (lt === -1) {
      if (stack.length === 0 && xml.slice(i).trim() !== "") fail("text outside root");
      break;
    }
    // Any "<" found IS a tag start by construction of indexOf; text
    // between tags must not contain a raw "&" that is not an entity.
    const text = xml.slice(i, lt);
    if (/(^|[^&])&(?!amp;|lt;|gt;|quot;|apos;|#)/.test(text)) fail("unescaped & in text");
    const gt = xml.indexOf(">", lt);
    if (gt === -1) fail("unterminated tag");
    const tag = xml.slice(lt + 1, gt);
    i = gt + 1;
    if (tag.startsWith("!--")) {
      if (!tag.endsWith("--")) fail("unterminated comment");
      continue;
    }
    if (tag.startsWith("!") || tag.startsWith("?")) continue; // doctype / PI
    if (tag.startsWith("/")) {
      const name = tag.slice(1).trim();
      if (stack.pop() !== name) fail(`closing </${name}> does not match open tag`);
      continue;
    }
    const selfClosing = tag.endsWith("/");
    const name = (selfClosing ? tag.slice(0, -1) : tag).trim().split(/\s/)[0];
    if (!name) fail("empty tag name");
    if (stack.length === 0) {
      roots++;
      if (roots > 1) fail("more than one root element");
    }
    if (!selfClosing) stack.push(name);
  }
  if (stack.length !== 0) fail(`unclosed element(s): ${stack.join(", ")}`);
  if (roots !== 1) fail("no root element");
}

// ------------------------------------------------------------------

const sheetFiles = readdirSync(FIXTURES)
  .filter((f) => f.endsWith(".sheet.json") && !f.startsWith("negative-"))
  .sort();

let passed = 0;
for (const f of sheetFiles) {
  const name = f.replace(".sheet.json", "");
  const sheet = JSON.parse(readFileSync(join(FIXTURES, f), "utf-8"));

  // Independent ground truth, computed from the fixture JSON alone.
  const cellIds = [];
  let declaredInputs = 0;
  for (const lane of sheet.lanes) {
    for (const cell of lane.cells) {
      cellIds.push(cell.id);
      declaredInputs += Object.keys(cell.inputs ?? {}).length;
    }
  }

  try {
    const svg = sheetToSvg(sheet); // (a) no throw
    for (const id of cellIds) {
      // (b) every cell id drawn
      if (!svg.includes(`data-cell="${id}"`) || !svg.includes(`>${id}<`)) {
        throw new Error(`cell id '${id}' missing from SVG`);
      }
    }
    const arrows = (svg.match(/<path class="pipe" /g) ?? []).length; // (c)
    if (arrows !== declaredInputs) {
      throw new Error(`arrow count ${arrows} != declared inputs ${declaredInputs}`);
    }
    checkXmlWellFormed(svg); // (d)
    passed++;
    console.log(
      `PASS ${name} (${cellIds.length} cells, ${arrows} arrows = ${declaredInputs} declared inputs)`
    );
  } catch (exc) {
    console.log(`FAIL ${name} -- ${exc.message}`);
  }
}

console.log(
  `DIAGRAM SUMMARY: ${passed}/${sheetFiles.length} PASS ` +
    `(no-throw, every cell id drawn, arrow count == declared-input count, XML well-formed)`
);
process.exit(passed === sheetFiles.length ? 0 : 1);
