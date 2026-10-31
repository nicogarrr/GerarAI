'use client';

import { useState } from 'react';
import Image from 'next/image';
import { Monitor, Smartphone, Tablet } from 'lucide-react';

import { useT } from '@/lib/i18n/client';

type Device = 'pc' | 'tablet' | 'movil';

/**
 * Mockup de la landing con selector de dispositivo (estilo Kymatio, pedido de
 * Nico 31-oct-2026): una sola maqueta cuyo marco y captura cambian entre PC,
 * tablet y móvil. Las capturas son reales de la app (fixture E2E etiquetado
 * como "Fuente de ejemplo" dentro de la propia interfaz). Los marcos de
 * tablet y móvil están dibujados en CSS (obra propia, sin assets de terceros).
 */
export default function LandingMockup() {
    const t = useT();
    const [device, setDevice] = useState<Device>('pc');

    const options = [
        { id: 'pc' as const, Icon: Monitor, label: t('landing.hero.devicePc') },
        { id: 'tablet' as const, Icon: Tablet, label: t('landing.hero.deviceTablet') },
        { id: 'movil' as const, Icon: Smartphone, label: t('landing.hero.deviceMobile') },
    ];

    return (
        <div className="relative mx-auto mt-12 max-w-5xl sm:mt-16">
            <div
                aria-hidden="true"
                className="pointer-events-none absolute -inset-x-16 -inset-y-16 -z-10 bg-[radial-gradient(ellipse_closest-side_at_50%_45%,rgba(45,212,191,0.14),transparent)]"
            />
            <div
                aria-label={t('landing.hero.deviceAria')}
                className="mb-5 inline-flex items-center gap-1 rounded-full border border-gray-700/60 bg-surface-1/80 p-1 shadow-lg shadow-black/30 backdrop-blur"
                role="group"
            >
                {options.map(({ id, Icon, label }) => (
                    <button
                        aria-pressed={device === id}
                        className={`inline-flex h-11 w-11 items-center justify-center rounded-full transition sm:h-12 sm:w-12 ${
                            device === id
                                ? 'bg-teal-400/15 text-teal-200 ring-1 ring-teal-400/40'
                                : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                        }`}
                        key={id}
                        onClick={() => setDevice(id)}
                        title={label}
                        type="button"
                    >
                        <Icon aria-hidden="true" className="h-5 w-5" />
                        <span className="sr-only">{label}</span>
                    </button>
                ))}
            </div>

            {device === 'pc' ? (
                <figure className="overflow-hidden rounded-xl border border-gray-700/60 bg-surface-1 shadow-2xl shadow-black/50">
                    <div
                        aria-hidden="true"
                        className="flex items-center gap-1.5 border-b border-gray-700/60 bg-surface-overlay px-4 py-2.5"
                    >
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-600" />
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-600" />
                        <span className="h-2.5 w-2.5 rounded-full bg-gray-600" />
                    </div>
                    <div className="relative aspect-[16/9]">
                        <div className="absolute inset-x-0 -top-16 h-[calc(100%+4rem)]">
                            <Image
                                alt={t('landing.hero.shotDesktopAlt')}
                                className="object-cover object-top"
                                fill
                                priority
                                sizes="(min-width: 1024px) 1024px, 100vw"
                                src="/landing/ficha-pc.png"
                            />
                        </div>
                    </div>
                </figure>
            ) : null}

            {device === 'tablet' ? (
                <figure className="mx-auto w-full max-w-xl">
                    <div className="rounded-[1.4rem] bg-gradient-to-br from-zinc-300 via-zinc-500 to-zinc-400 p-[2px] shadow-2xl shadow-black/80">
                        <div className="relative rounded-[1.3rem] bg-black p-[10px]">
                            <div
                                aria-hidden="true"
                                className="absolute left-[4px] top-1/2 z-20 h-[4px] w-[4px] -translate-y-1/2 rounded-full bg-zinc-700"
                            />
                            <div className="relative aspect-[4/3] overflow-hidden rounded-[0.7rem] bg-surface-1">
                                <Image
                                    alt={t('landing.hero.shotTabletAlt')}
                                    className="object-cover"
                                    fill
                                    sizes="(min-width: 640px) 576px, 100vw"
                                    src="/landing/ficha-tablet.png"
                                />
                                <div
                                    aria-hidden="true"
                                    className="pointer-events-none absolute inset-0 bg-[linear-gradient(115deg,rgba(255,255,255,0.07)_0%,rgba(255,255,255,0)_38%)]"
                                />
                            </div>
                        </div>
                    </div>
                </figure>
            ) : null}

            {device === 'movil' ? (
                <figure className="mx-auto w-44 sm:w-56">
                    <div className="rounded-[1.9rem] bg-gradient-to-br from-zinc-300 via-zinc-500 to-zinc-400 p-[1.5px] shadow-2xl shadow-black/60 sm:rounded-[2.4rem]">
                        <div className="relative rounded-[1.8rem] bg-black p-[4px] sm:rounded-[2.3rem] sm:p-[5px]">
                            <div className="relative aspect-[390/903] overflow-hidden rounded-[1.5rem] bg-black sm:rounded-[2rem]">
                                {/* Barra de estado tipo iOS: la isla vive aquí y la app empieza debajo. */}
                                <div
                                    aria-hidden="true"
                                    className="absolute inset-x-0 top-0 z-10 flex h-[6.5%] items-center justify-between px-[9%] text-[5px] font-semibold leading-none text-white sm:text-[7px]"
                                >
                                    <span>9:41</span>
                                    <span className="flex items-center gap-[2px]">
                                        <span className="flex items-end gap-[1px]">
                                            <i className="block h-[2px] w-[1.5px] bg-white" />
                                            <i className="block h-[3px] w-[1.5px] bg-white" />
                                            <i className="block h-[4px] w-[1.5px] bg-white" />
                                        </span>
                                        <span className="block h-[4px] w-[8px] rounded-[1.5px] border border-white/70 p-[0.5px] sm:h-[5px] sm:w-[11px]">
                                            <i className="block h-full w-[75%] rounded-[0.5px] bg-white" />
                                        </span>
                                    </span>
                                </div>
                                <div
                                    aria-hidden="true"
                                    className="absolute left-1/2 top-[1.3%] z-20 h-[4.1%] w-[30%] -translate-x-1/2 rounded-full bg-black ring-1 ring-zinc-800"
                                />
                                <div className="absolute inset-x-0 bottom-0 aspect-[390/844]">
                                    <Image
                                        alt={t('landing.hero.shotMobileAlt')}
                                        className="object-cover"
                                        fill
                                        sizes="(min-width: 640px) 224px, 176px"
                                        src="/landing/ficha-movil.png"
                                    />
                                </div>
                            </div>
                        </div>
                    </div>
                </figure>
            ) : null}
        </div>
    );
}
