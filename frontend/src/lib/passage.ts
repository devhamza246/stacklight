/** Tiny, safe structure pass over a chunk's markdown: pipe tables and paragraphs only. No HTML is ever produced. */
export interface Seg { text: string; start: number }
export interface Row { cells: Seg[]; header: boolean; start: number; end: number }
export type Block = { kind: "table"; rows: Row[] } | { kind: "text"; seg: Seg } | { kind: "heading"; seg: Seg };

const isTableLine = (l: string) => l.trim().startsWith("|");
const isSeparator = (l: string) => /^\s*\|[\s:|-]+\|?\s*$/.test(l) && l.includes("-");

function cellsOf(line: string, offset: number): Seg[] {
  const out: Seg[] = [];
  let from = line.indexOf("|") + 1;
  while (from > 0 && from <= line.length) {
    let to = line.indexOf("|", from);
    if (to < 0) to = line.length;
    const raw = line.slice(from, to);
    const text = raw.trim();
    if (to === line.length && !text) break; // trailing pipe
    out.push({ text, start: offset + from + raw.indexOf(text || raw) });
    from = to + 1;
  }
  return out;
}

export function parsePassage(text: string): Block[] {
  const blocks: Block[] = [];
  let pos = 0;
  let para: { start: number; end: number } | null = null;
  let table: Row[] | null = null;
  const flushPara = () => {
    if (para) blocks.push({ kind: "text", seg: { text: text.slice(para.start, para.end), start: para.start } });
    para = null;
  };
  const flushTable = () => {
    if (table?.length) blocks.push({ kind: "table", rows: table });
    table = null;
  };
  for (const line of text.split("\n")) {
    const start = pos;
    const end = pos + line.length;
    pos = end + 1;
    if (isTableLine(line)) {
      flushPara();
      table ??= [];
      if (isSeparator(line)) {
        if (table.length) table[table.length - 1].header = true;
      } else {
        table.push({ cells: cellsOf(line, start), header: false, start, end });
      }
    } else if (/^#{1,6}\s/.test(line)) {
      flushPara();
      flushTable();
      const hashes = line.match(/^#{1,6}\s+/)![0].length;
      blocks.push({ kind: "heading", seg: { text: line.slice(hashes), start: start + hashes } });
    } else if (!line.trim()) {
      flushPara();
      flushTable();
    } else {
      flushTable();
      para = para ? { start: para.start, end } : { start, end };
    }
  }
  flushPara();
  flushTable();
  return blocks;
}

/** Split `seg` around the highlighted range [r0, r1): [before, marked, after]. */
export function splitAround(seg: Seg, range: [number, number] | null): [string, string, string] {
  if (!range) return [seg.text, "", ""];
  const a = Math.max(range[0], seg.start) - seg.start;
  const b = Math.min(range[1], seg.start + seg.text.length) - seg.start;
  if (b <= a) return [seg.text, "", ""];
  return [seg.text.slice(0, a), seg.text.slice(a, b), seg.text.slice(b)];
}
