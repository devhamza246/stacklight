import { findQuote } from "../lib/quote";
import { parsePassage, splitAround, type Seg } from "../lib/passage";

function Marked({ seg, range }: { seg: Seg; range: [number, number] | null }) {
  const [before, hit, after] = splitAround(seg, range);
  if (!hit) return <>{seg.text}</>;
  return <>{before}<mark>{hit}</mark>{after}</>;
}

/** A corpus passage with the cited sentence highlighted. Text only: tables become <table>, everything else <p>. */
export function PassageView({ text, quote }: { text: string; quote?: string }) {
  const range = quote ? findQuote(text, quote) : null;
  const blocks = parsePassage(text);
  return (
    <div className="passage" data-testid="passage">
      {blocks.map((b, i) =>
        b.kind === "heading" ? (
          <h4 key={i} className="passage-h"><Marked seg={b.seg} range={range} /></h4>
        ) : b.kind === "text" ? (
          <p key={i} className="passage-text"><Marked seg={b.seg} range={range} /></p>
        ) : (
          <div key={i} className="passage-table">
            <table>
              <tbody>
                {b.rows.map((r, j) => {
                  const cited = range !== null && r.start < range[1] && r.end > range[0];
                  return (
                    <tr key={j} className={cited ? "cited" : undefined}>
                      {r.cells.map((c, k) => {
                        const Cell = r.header ? "th" : "td";
                        return <Cell key={k}><Marked seg={c} range={range} /></Cell>;
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ),
      )}
    </div>
  );
}

export function quoteFound(text: string, quote?: string): boolean {
  return !!quote && findQuote(text, quote) !== null;
}
