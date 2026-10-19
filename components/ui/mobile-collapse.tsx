'use client';

import * as React from 'react';
import { ChevronDown } from 'lucide-react';

/** Bloque plegado en móvil (cerrado por defecto) y siempre visible desde `md`. */
export default function MobileCollapse({ title, children }: { title: string; children: React.ReactNode }) {
    const [open, setOpen] = React.useState(false);
    const id = React.useId();
    return (
        <div>
            <button
                aria-controls={id}
                aria-expanded={open}
                className="flex min-h-[44px] w-full items-center justify-between rounded-xl border border-gray-800 bg-surface-1 px-4 text-left text-sm font-semibold text-gray-100 md:hidden"
                onClick={() => setOpen((value) => !value)}
                type="button"
            >
                {title}
                <ChevronDown aria-hidden="true" className={`h-5 w-5 text-gray-500 transition-transform ${open ? 'rotate-180' : ''}`} />
            </button>
            <div className={open ? 'mt-3 block' : 'hidden md:block'} id={id}>{children}</div>
        </div>
    );
}
