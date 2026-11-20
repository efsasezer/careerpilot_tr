import { CircleCheck, CircleX, Undo2 } from "lucide-react";
import { useClearVerification, useSetVerification } from "../../services/api/hooks";
import type { Verification } from "../../types/api";

/** "Doğruladım: Uygun / Uygun değil" ve geri alma. Karar sunucuda sistem kararından ayrı saklanır. */
export function VerifyButtons({
  jobId, positionId = "", verification, note, compact = false,
}: {
  jobId: number;
  positionId?: string;
  verification: Verification | null;
  note?: string;
  compact?: boolean;
}) {
  const set = useSetVerification();
  const clear = useClearVerification();
  const busy = set.isPending || clear.isPending;
  const current = verification?.decision ?? null;
  const decide = (decision: "eligible" | "not_eligible") =>
    set.mutate({ jobId, decision, position_id: positionId, note: note ?? verification?.note ?? "" });

  return (
    <div className={`verify ${compact ? "verify-compact" : ""}`} onClick={(event) => event.stopPropagation()}>
      <button type="button" className={`button button-small ${current === "eligible" ? "button-ok" : ""}`} disabled={busy} onClick={() => decide("eligible")}>
        <CircleCheck size={15} /> {compact ? "Uygun" : "Doğruladım: Uygun"}
      </button>
      <button type="button" className={`button button-small ${current === "not_eligible" ? "button-bad" : ""}`} disabled={busy} onClick={() => decide("not_eligible")}>
        <CircleX size={15} /> {compact ? "Uygun değil" : "Doğruladım: Uygun değil"}
      </button>
      {current && (
        <button type="button" className="button button-small" disabled={busy} onClick={() => clear.mutate({ jobId, position_id: verification?.scope === "position" ? positionId : "" })}>
          <Undo2 size={15} /> {compact ? "Geri al" : "Doğrulamayı geri al"}
        </button>
      )}
      {(set.error || clear.error) && <span className="field-error" role="alert">{(set.error ?? clear.error)!.message}</span>}
    </div>
  );
}
