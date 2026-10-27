'use client';

import { useEffect, useRef, type ReactNode } from 'react';

/** Native disclosure keeps forms mounted and supports direct settings links. */
export default function SettingsSection({ id, title, description, children }: {
  id: string; title: string; description: string; children: ReactNode;
}) {
  const ref = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const reveal = () => {
      if (window.location.hash === `#${id}` && ref.current) {
        ref.current.open = true;
      }
    };
    const onAnchorClick = (event: MouseEvent) => {
      const anchor = event.target instanceof Element ? event.target.closest('a') : null;
      if (anchor?.getAttribute('href') === `#${id}` && ref.current) ref.current.open = true;
    };
    reveal();
    document.addEventListener('click', onAnchorClick);
    window.addEventListener('hashchange', reveal);
    return () => {
      window.removeEventListener('hashchange', reveal);
      document.removeEventListener('click', onAnchorClick);
    };
  }, [id]);
  return (
    <details className="scroll-mt-24 rounded-xl border border-gray-700/50 bg-surface-1 p-5" id={id} ref={ref}>
      <summary className="min-h-11 cursor-pointer text-gray-100 marker:text-teal-300">
        <span className="ml-1 text-base font-semibold">{title}</span>
        <span className="mt-1 block text-sm text-gray-400">{description}</span>
      </summary>
      <div className="mt-5">{children}</div>
    </details>
  );
}
