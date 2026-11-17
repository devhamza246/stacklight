import type { DocRef } from "../api/types";
import { basename } from "../lib/format";
import { renderBold } from "../lib/boldSplit";

interface Props {
  target: DocRef;
  find: string;
  replace: string;
  replaceAll: boolean;
  /** The document whose wording the fix adopts; its text is `replace`. */
  support?: DocRef;
}

/**
 * The exact edit the Curator proposes: the sentence to remove (red, `−`) and the one to put in
 * its place (green, `+`). All text is LLM- or corpus-authored and is rendered as text nodes;
 * only `**…**` runs become <strong>, so no HTML can be injected.
 */
export function DocDiff({ target, find, replace, replaceAll, support }: Props) {
  return (
    <div className="docdiff">
      {support && (
        <div className="diff two">
          <div className="diff-side">
            <div className="diff-file"><span className="mono">{basename(support.source)}</span><span>Wording to keep</span></div>
            <div className="diff-line keep"><mark>{renderBold(replace)}</mark></div>
          </div>
          <div className="diff-side is-wrong">
            <div className="diff-file"><span className="mono">{basename(target.source)}</span><span>Wording to replace</span></div>
            <div className="diff-line"><mark>{renderBold(find)}</mark></div>
          </div>
        </div>
      )}
      <div className="fix" role="group" aria-label={`Proposed fix in ${basename(target.source)}`}>
        <div className="fix-title">Proposed fix in {basename(target.source)}</div>
        <div className="fix-row del"><span className="g" aria-label="Removed">−</span><span>{renderBold(find)}</span></div>
        <div className="fix-row add"><span className="g" aria-label="Added">+</span><span>{renderBold(replace)}</span></div>
      </div>
      <p className="q-scope">
        Scope: 1 file, <span className="mono">{basename(target.source)}</span>.{" "}
        {replaceAll ? (
          <span className="badge badge-warn"><strong>replace_all ON</strong> every occurrence in the file changes</span>
        ) : (
          <>One exact-match edit, <span className="mono">replace_all</span> off.</>
        )}
      </p>
    </div>
  );
}
