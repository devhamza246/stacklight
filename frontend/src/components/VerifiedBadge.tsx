import type { VerifiedEvent } from "../api/types";
import { Icon } from "./Icon";

/** Fact-check result for an answer. `verified === null` means the Fact-checker is still working. */
export function VerifiedBadge({ verified }: { verified: VerifiedEvent | null }) {
  if (!verified) {
    return <span className="badge badge-neutral" role="status"><Icon name="clock" />Verifying sources…</span>;
  }
  const all = verified.claims_supported >= verified.claims_total;
  return (
    <span className={`badge ${all ? "badge-ok" : "badge-warn"}`}>
      <Icon name="shield" />
      Fact-checked · {verified.claims_supported}/{verified.claims_total} claims supported
    </span>
  );
}
