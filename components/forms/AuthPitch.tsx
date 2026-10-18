import Link from 'next/link';
import { ArrowRight } from 'lucide-react';

import { productModules } from '@/lib/config/product';

/**
 * Contexto de producto para las pantallas de acceso.
 *
 * `/sign-in` mostraba un formulario y un H1, sin decir qué es GerarAI ni qué
 * se obtiene. Este bloque se pinta encima del formulario (sin quitarlo) con los
 * tres módulos del producto y un enlace a la metodología.
 *
 * Sin estado ni efectos: son enlaces. Se importa también desde páginas cliente
 * (`sign-in`, `sign-up`), así que no puede leer `process.env` del servidor.
 */
export default function AuthPitch({ className = '' }: { className?: string }) {
    return (
        <div className={className}>
            <ul className="space-y-2">
                {productModules.map(({ icon: ModuleIcon, title, description }) => (
                    <li className="flex items-start gap-2.5" key={title}>
                        <ModuleIcon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-teal-300" />
                        <span className="text-sm leading-6 text-gray-400">
                            <span className="font-medium text-gray-300">{title}.</span> {description}
                        </span>
                    </li>
                ))}
            </ul>
            <div className="mt-4 flex flex-col gap-2 text-sm">
                <Link
                    href="/metodologia"
                    className="inline-flex min-h-11 items-center gap-1 text-gray-400 underline-offset-4 hover:text-teal-300 hover:underline"
                >
                    Cómo funciona: metodología y fuentes de datos
                    <ArrowRight aria-hidden="true" className="h-4 w-4" />
                </Link>
            </div>
        </div>
    );
}
