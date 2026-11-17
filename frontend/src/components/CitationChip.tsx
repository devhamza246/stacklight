interface Props {
  n: number;
  title: string;
  expanded: boolean;
  onOpen: (el: HTMLButtonElement) => void;
}

/** `[n]` chip that opens the source drawer. The label names the source for screen readers. */
export function CitationChip({ n, title, expanded, onOpen }: Props) {
  return (
    <button
      className="cite"
      type="button"
      aria-haspopup="dialog"
      aria-controls="source-drawer"
      aria-expanded={expanded}
      aria-label={`Source ${n}: ${title}`}
      onClick={(e) => onOpen(e.currentTarget)}
    >
      [{n}]
    </button>
  );
}
