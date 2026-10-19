import type { Metadata } from 'next';
import Link from 'next/link';

export const metadata: Metadata = {
    title: 'Aprender - GerarAI',
    description: 'Cartas, vídeos, conceptos y canales para aprender de los mejores inversores.',
};

// Índice de la pestaña Aprender del hub Inversores/Señales (Opción A, decisión
// de Nico, WhatsApp 2026-10-20 00:59). PR 3: Cartas, Vídeos, Conceptos y
// Canales se fusionan aquí como sub-pestañas y las rutas viejas redirigen.
const SECTIONS = [
    { href: '/inversores/cartas', title: 'Cartas', text: 'Cartas a accionistas de los grandes gestores, comentadas.' },
    { href: '/inversores/videos', title: 'Vídeos', text: 'Charlas y entrevistas con los inversores que sigues.' },
    { href: '/inversores/conceptos', title: 'Conceptos', text: 'Las ideas clave de value investing, explicadas.' },
    { href: '/inversores/canales', title: 'Canales', text: 'Canales de análisis que merece la pena seguir.' },
];

export default function AprenderPage() {
    return (
        <main className="mx-auto flex w-full min-w-0 max-w-5xl flex-col gap-6 overflow-x-clip py-6" id="content" tabIndex={-1}>
            <header className="flex flex-col gap-1">
                <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">Aprender</h1>
                <p className="text-base text-gray-400">Cartas, vídeos, conceptos y canales para aprender de los mejores.</p>
            </header>
            <ul className="grid gap-3 sm:grid-cols-2">
                {SECTIONS.map((section) => (
                    <li key={section.href}>
                        <Link
                            className="flex h-full flex-col gap-1 rounded-2xl border border-gray-800 bg-surface-1 p-6 transition-colors hover:border-gray-700"
                            href={section.href}
                        >
                            <span className="text-base font-medium text-gray-100">{section.title}</span>
                            <span className="text-sm text-gray-400">{section.text}</span>
                        </Link>
                    </li>
                ))}
            </ul>
        </main>
    );
}
