import { Fragment, type ReactNode } from "react";

/**
 * Split text on `**` markers and render the enclosed runs as <strong>.
 * Everything stays a React text node, so any HTML in the input is shown literally.
 * An unmatched trailing marker stays literal.
 */
export function renderBold(text: string): ReactNode {
  const parts = text.split("**");
  if (parts.length < 3) return text;
  const matched = parts.length % 2 === 1 ? parts.length : parts.length - 1; // a dangling opener is literal
  const nodes: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (i >= matched) nodes.push(`**${part}`);
    else if (i % 2 === 1) nodes.push(<strong key={i}>{part}</strong>);
    else if (part) nodes.push(<Fragment key={i}>{part}</Fragment>);
  });
  return <>{nodes}</>;
}
