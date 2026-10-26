// Sheet visualiser for SuperInstance lane-sheets -- a pure function
// from a parsed lane sheet to an SVG string. No DOM, no dependencies:
// the same module runs in the browser (the deployment page inlines its
// output) and under Node (check_diagram.mjs asserts its correctness
// over the whole fixture corpus).
//
// Correctness before prettiness -- the drawing's contract:
//   * Columns are topological depth: a cell's depth is 0 when it pipes
//     from nothing, else 1 + the max depth of the cells it pipes from.
//   * Rows are grouped into labelled bands by lane prefix -- the part
//     of the cell id before the first "." -- and cells keep canonical
//     order (depth, then sheet order) within a band.
//   * Arrows are drawn for DECLARED inputs only: one curved arrow per
//     entry of a cell's `inputs` map, labelled with the input (port)
//     name. Template placeholders that are not declared inputs are not
//     piping and draw nothing -- that distinction is the format's
//     whole point, so the drawing keeps it exact.
//   * A `sheet` cell is double-bordered and names the sheet it
//     contains; an `each`-mode sheet cell additionally names the port
//     it fans out over and is drawn with stacked offset outlines.

const KIND_COLORS = {
  value: "#7d9b76", // muted sage
  prompt: "#6f8faf", // muted slate blue
  llm: "#a583b5", // muted violet
  tool: "#c08a4e", // muted ochre
  branch: "#b56a6a", // muted brick
  sheet: "#4e9a94", // muted teal
};
const FALLBACK_COLOR = "#8a9199";

const MONO = "ui-monospace, 'SF Mono', Menlo, Consolas, monospace";
const ID_FONT = 13; // px, bold
const SUB_FONT = 11; // px
const ID_CHAR_W = 7.9; // monospace advance at ID_FONT, with slack
const SUB_CHAR_W = 6.7;

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function lanePrefix(cellId) {
  const dot = cellId.indexOf(".");
  return dot === -1 ? cellId : cellId.slice(0, dot);
}

function extraLines(cell) {
  const lines = [];
  if (cell.kind === "sheet") {
    lines.push(`∋ sheet: ${cell.sheet ?? ""}`);
    if (Object.prototype.hasOwnProperty.call(cell, "each")) {
      lines.push(`× each over ${cell.each}`);
    }
  }
  return lines;
}

function boxHeight(cell) {
  // id line + kind line + one line per extra (sheet ref, each note)
  return 22 + (2 + extraLines(cell).length) * 16;
}

export function sheetToSvg(sheet) {
  const cells = [];
  for (const lane of sheet.lanes ?? []) {
    for (const cell of lane.cells ?? []) cells.push(cell);
  }
  if (cells.length === 0) {
    return (
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 60" ` +
      `font-family="${MONO}"><text x="16" y="36" font-size="12" fill="#5a6169">` +
      `no cells to draw</text></svg>`
    );
  }
  const byId = new Map(cells.map((c) => [c.id, c]));
  const flatPos = new Map(cells.map((c, i) => [c.id, i]));

  // ---- topological depth (cycle-guarded) -------------------------
  const depth = new Map();
  function depthOf(id, stack) {
    if (depth.has(id)) return depth.get(id);
    if (stack.has(id)) {
      throw new Error(`CycleDetected: piping cycle through cell '${id}'`);
    }
    const cell = byId.get(id);
    if (!cell) throw new Error(`UnknownInputCell: '${id}'`);
    stack.add(id);
    const sources = Object.values(cell.inputs ?? {}).filter((s) => byId.has(s));
    const d = sources.length === 0 ? 0 : 1 + Math.max(...sources.map((s) => depthOf(s, stack)));
    stack.delete(id);
    depth.set(id, d);
    return d;
  }
  for (const c of cells) depthOf(c.id, new Set());
  const maxDepth = Math.max(...depth.values());

  // ---- canonical order: depth, then sheet order ------------------
  const canonical = [...cells].sort(
    (a, b) => depth.get(a.id) - depth.get(b.id) || flatPos.get(a.id) - flatPos.get(b.id)
  );

  // ---- lane bands, in first-canonical-appearance order -----------
  const bandNames = [];
  const bandCells = new Map();
  for (const cell of canonical) {
    const prefix = lanePrefix(cell.id);
    if (!bandCells.has(prefix)) {
      bandCells.set(prefix, []);
      bandNames.push(prefix);
    }
    bandCells.get(prefix).push(cell);
  }

  // ---- geometry ---------------------------------------------------
  let maxText = 0;
  for (const cell of cells) {
    maxText = Math.max(maxText, cell.id.length * ID_CHAR_W);
    for (const line of extraLines(cell)) {
      maxText = Math.max(maxText, line.length * SUB_CHAR_W);
    }
  }
  const boxW = Math.min(430, Math.max(168, Math.ceil(maxText + 40)));
  const colGap = 86;
  const rowGap = 20;
  const marginX = 20;
  const headerH = 38;
  const bandHeaderH = 24;
  const bandPadBottom = 10;
  const bandGap = 12;
  const maxBoxH = Math.max(...cells.map(boxHeight));

  const width = Math.max(
    480,
    marginX * 2 + (maxDepth + 1) * boxW + maxDepth * colGap
  );

  // Per band: assign each cell the first sub-row whose slot at the
  // cell's depth is still free (cells in a band share a row whenever
  // their columns differ).
  const pos = new Map(); // id -> {x, y, w, h, band}
  const bandGeom = []; // {name, y, h}
  let bandY = headerH;
  for (const name of bandNames) {
    const list = bandCells.get(name);
    const rows = []; // rows[r] = Set of depths taken
    const subrow = new Map();
    for (const cell of list) {
      const d = depth.get(cell.id);
      let r = 0;
      while (rows[r] && rows[r].has(d)) r++;
      if (!rows[r]) rows[r] = new Set();
      rows[r].add(d);
      subrow.set(cell.id, r);
    }
    const nRows = rows.length;
    const h = bandHeaderH + nRows * maxBoxH + (nRows - 1) * rowGap + bandPadBottom;
    for (const cell of list) {
      pos.set(cell.id, {
        x: marginX + depth.get(cell.id) * (boxW + colGap),
        y: bandY + bandHeaderH + subrow.get(cell.id) * (maxBoxH + rowGap),
        w: boxW,
        h: boxHeight(cell),
        band: name,
      });
    }
    bandGeom.push({ name, y: bandY, h });
    bandY += h + bandGap;
  }
  const bandsBottom = bandY - bandGap;

  // ---- legend (wraps to the computed width) -----------------------
  const legendEntries = Object.entries(KIND_COLORS);
  const legendItems = legendEntries.map(([kind, color]) => ({
    kind,
    color,
    w: 14 + 6 + kind.length * SUB_CHAR_W + 20,
  }));
  let legendRows = 1;
  {
    let x = marginX + 44; // after the "kind:" caption
    for (const item of legendItems) {
      if (x + item.w > width - marginX) {
        legendRows++;
        x = marginX + 44;
      }
      x += item.w;
    }
  }
  const legendH = legendRows * 20 + 8;
  const height = bandsBottom + 10 + legendH + 6;

  // ---- emit --------------------------------------------------------
  const out = [];
  const title = sheet.title ? `${sheet.id ?? "sheet"}: ${sheet.title}` : (sheet.id ?? "lane sheet");
  out.push(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" ` +
      `width="${width}" height="${height}" role="img" aria-label="${esc(title)}" ` +
      `font-family="${MONO}">`
  );
  out.push(`<title>${esc(title)}</title>`);
  out.push(
    `<defs><marker id="pipe-arrow" viewBox="0 0 8 8" refX="7.5" refY="4" ` +
      `markerWidth="7" markerHeight="7" orient="auto-start-reverse">` +
      `<path d="M0,0 L8,4 L0,8 z" fill="#5a6169"/></marker></defs>`
  );
  out.push(
    `<text x="${marginX}" y="24" font-size="15" font-weight="bold" fill="#1a1d21">${esc(sheet.id ?? "lane sheet")}</text>`
  );

  // Lane bands: labelled background rows.
  bandGeom.forEach((band, i) => {
    out.push(
      `<rect x="8" y="${band.y}" width="${width - 16}" height="${band.h}" rx="8" ` +
        `fill="${i % 2 === 0 ? "#f6f7f9" : "#eef1f4"}" stroke="#d9dde2"/>`
    );
    out.push(
      `<text x="${marginX + 2}" y="${band.y + 16}" font-size="11" font-weight="bold" ` +
        `letter-spacing="0.08em" fill="#5a6169">${esc(band.name)}</text>`
    );
  });

  // Piping arrows (declared inputs only), under the boxes; their
  // labels are emitted after the boxes so they stay readable.
  const labels = [];
  for (const cell of cells) {
    const target = pos.get(cell.id);
    const x2 = target.x;
    const y2 = target.y + target.h / 2;
    for (const [port, sourceId] of Object.entries(cell.inputs ?? {})) {
      const source = pos.get(sourceId);
      if (!source) continue;
      const x1 = source.x + source.w;
      const y1 = source.y + source.h / 2;
      const dx = Math.max(38, Math.abs(x2 - x1) * 0.45);
      out.push(
        `<path class="pipe" d="M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}" ` +
          `fill="none" stroke="#5a6169" stroke-width="1.4" marker-end="url(#pipe-arrow)"/>`
      );
      // Label near the target end of the curve (t = 0.85): the last
      // stretch of every arrow crosses the free column gap, so the
      // port name sits in open space and reads as the target's input.
      const t = 0.85;
      const mt = 1 - t;
      const lx =
        mt ** 3 * x1 + 3 * mt * mt * t * (x1 + dx) + 3 * mt * t * t * (x2 - dx) + t ** 3 * x2;
      const ly =
        mt ** 3 * y1 + 3 * mt * mt * t * y1 + 3 * mt * t * t * y2 + t ** 3 * y2;
      labels.push(
        `<text class="pipe-label" x="${lx.toFixed(1)}" y="${(ly - 6).toFixed(1)}" ` +
          `font-size="10" text-anchor="middle" fill="#3d434a" ` +
          `style="paint-order:stroke" stroke="#ffffff" stroke-width="3">${esc(port)}</text>`
      );
    }
  }
  out.push(...labels);

  // Cells.
  for (const cell of canonical) {
    const p = pos.get(cell.id);
    const color = KIND_COLORS[cell.kind] ?? FALLBACK_COLOR;
    const extras = extraLines(cell);
    const isEach = cell.kind === "sheet" && extras.length > 1;
    out.push(`<g class="cell" data-cell="${esc(cell.id)}" data-kind="${esc(cell.kind)}">`);
    if (isEach) {
      for (const off of [7, 3.5]) {
        out.push(
          `<rect x="${p.x + off}" y="${p.y + off}" width="${p.w}" height="${p.h}" rx="8" ` +
            `fill="none" stroke="#9aa3ad" stroke-width="1"/>`
        );
      }
    }
    out.push(
      `<rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="8" ` +
        `fill="#ffffff" stroke="#3d434a" stroke-width="1.5"/>`
    );
    if (cell.kind === "sheet") {
      out.push(
        `<rect x="${p.x + 4}" y="${p.y + 4}" width="${p.w - 8}" height="${p.h - 8}" rx="5" ` +
          `fill="none" stroke="${color}" stroke-width="1.2"/>`
      );
    }
    out.push(
      `<path class="kind-edge" d="M ${p.x + 4} ${p.y + 7} V ${p.y + p.h - 7}" ` +
        `stroke="${color}" stroke-width="6" stroke-linecap="round"/>`
    );
    out.push(
      `<text x="${p.x + 16}" y="${p.y + 22}" font-size="${ID_FONT}" font-weight="bold" ` +
        `fill="#1a1d21">${esc(cell.id)}</text>`
    );
    out.push(
      `<text x="${p.x + 16}" y="${p.y + 38}" font-size="${SUB_FONT}" fill="#5a6169">${esc(cell.kind)}</text>`
    );
    extras.forEach((line, i) => {
      out.push(
        `<text x="${p.x + 16}" y="${p.y + 54 + i * 16}" font-size="${SUB_FONT}" ` +
          `fill="${color}">${esc(line)}</text>`
      );
    });
    out.push(`</g>`);
  }

  // Legend.
  let lx = marginX;
  let ly = bandsBottom + 10;
  out.push(
    `<text x="${lx}" y="${ly + 11}" font-size="${SUB_FONT}" fill="#5a6169">kind:</text>`
  );
  lx += 44;
  for (const item of legendItems) {
    if (lx + item.w > width - marginX) {
      lx = marginX + 44;
      ly += 20;
    }
    out.push(
      `<rect x="${lx}" y="${ly + 1}" width="12" height="12" rx="3" fill="${item.color}"/>`
    );
    out.push(
      `<text x="${lx + 17}" y="${ly + 11}" font-size="${SUB_FONT}" fill="#3d434a">${esc(item.kind)}</text>`
    );
    lx += item.w;
  }

  out.push(`</svg>`);
  return out.join("\n");
}

export const DIAGRAM_KIND_COLORS = KIND_COLORS;
