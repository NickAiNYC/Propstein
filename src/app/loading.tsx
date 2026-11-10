/**
 * PropStein — route loading state (terminal skeleton, dark themed).
 */
export default function Loading() {
  return (
    <div className="min-h-screen bg-[#090A0F] flex items-center justify-center" role="status" aria-label="Loading terminal">
      <div className="flex flex-col items-center gap-3">
        <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 pst-pulse" aria-hidden="true" />
        <p className="text-[12px] text-zinc-600 pst-num">loading terminal surfaces…</p>
      </div>
    </div>
  );
}
