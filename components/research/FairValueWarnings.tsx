import { fairValueWarnings } from '@/lib/research/fair-value-warnings';

/** Quiet, always-visible caveats next to the value, not a repeated live alert. */
export default function FairValueWarnings({ warnings, label }: { warnings?: unknown; label: string }) {
  const items = fairValueWarnings(warnings);
  if (!items.length) return null;
  return (
    <ul aria-label={label} className="mt-1 min-w-0 list-disc space-y-1 break-words pl-4 text-xs leading-5 text-amber-200/90" data-testid="fair-value-warnings">
      {items.map((warning) => <li key={warning}>{warning}</li>)}
    </ul>
  );
}
