import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { DocRef } from "../api/types";

/** Title/path lookup for document ids named in approval payloads. Cached; failures degrade to "Document #id". */
export function useDocs(ids: number[], fetchDocs: (ids: number[]) => Promise<DocRef[]> = api.documents): Record<number, DocRef> {
  const [docs, setDocs] = useState<Record<number, DocRef>>({});
  const asked = useRef(new Set<number>());
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const key = [...new Set(ids)].sort((a, b) => a - b).join(",");

  useEffect(() => {
    const need = key ? key.split(",").map(Number).filter((id) => !asked.current.has(id)) : [];
    if (!need.length) return;
    need.forEach((id) => asked.current.add(id));
    fetchDocs(need).then(
      (list) => mounted.current && setDocs((d) => ({ ...d, ...Object.fromEntries(list.map((x) => [x.id, x])) })),
      () => { need.forEach((id) => asked.current.delete(id)); },
    );
  }, [key, fetchDocs]);

  return docs;
}

export const docLabel = (docs: Record<number, DocRef>, id: number): DocRef =>
  docs[id] ?? { id, title: `Document #${id}`, source: `document-${id}` };
