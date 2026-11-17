/**
 * Locate `quote` inside `text` ignoring whitespace differences (the backend validates quotes
 * whitespace-normalised). Returns [start, end) offsets into the ORIGINAL text, or null.
 */
export function findQuote(text: string, quote: string): [number, number] | null {
  const q = quote.replace(/\s+/g, " ").trim();
  if (!q) return null;
  let flat = "";
  const origin: number[] = []; // index in `flat` -> index in `text`
  let prevSpace = true;
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) {
      if (!prevSpace) { flat += " "; origin.push(i); }
      prevSpace = true;
    } else {
      flat += text[i]; origin.push(i); prevSpace = false;
    }
  }
  const at = flat.indexOf(q);
  if (at < 0) return null;
  return [origin[at], origin[at + q.length - 1] + 1];
}
