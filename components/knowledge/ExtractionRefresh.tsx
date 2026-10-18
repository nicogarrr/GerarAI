'use client';
import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
/** A terminal server render sets active=false and cancels the pending refresh. */
export function ExtractionRefresh({ active }: { active: boolean }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return;
    let timer: number;
    let delay = 30_000;
    const schedule = () => {
      timer = window.setTimeout(() => {
        if (document.visibilityState === 'visible') {
          router.refresh();
          delay = Math.min(60_000, delay * 2);
        }
        schedule();
      }, delay);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [active, router]);
  return null;
}
