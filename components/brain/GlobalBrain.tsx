'use client';

import { useState, useRef, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { X, Send, User, Bot, Loader2, Maximize2, Minimize2 } from 'lucide-react';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { chatWithPortfolio } from '@/lib/actions/brain.actions';
import { brainPageContext } from '@/lib/brain/page-context';
import ReactMarkdown from 'react-markdown';
import type { PortfolioChatCitation } from '@/lib/chat/citations';
import { BrainSources } from './BrainSources';

interface Message {
    role: 'user' | 'assistant';
    content: string;
    citations?: PortfolioChatCitation[];
}

interface GlobalBrainProps {
    userId: string;
}

type ContextEcho = {
    label: string;
    ticker: string | null;
    company_name: string | null;
    company_resolved: boolean;
};

/**
 * Cerebro global de GerarAI, montado UNA vez en el layout autenticado:
 * panel lateral en escritorio y botón fijo en móvil que nunca tapa la
 * BottomNav. Cada pregunta lleva el contexto de página explícito (pastilla
 * "Viendo X"); el eco que devuelve el servidor (IDs resueltos y permisos
 * aplicados allí) manda sobre la etiqueta local. Solo lectura.
 */
/** Selector de controles que el FAB no puede tapar en reposo: lo que el
 *  usuario podria querer pulsar justo debajo de la burbuja. */
const FAB_INTERACTIVE_SELECTOR =
    'a[href], button, input, select, textarea, summary, [role="button"], [role="link"], [contenteditable="true"]';

/** ¿El FAB tapa un control interactivo en reposo? Se mira que hay justo
 *  debajo de su zona (centro y esquinas interiores) con elementsFromPoint,
 *  descartando el propio FAB y su icono. La zona se mide desde el computed
 *  style (bottom/right resuelven env(safe-area-inset-*) a px), igual que el
 *  chequeo de la leyenda: con el translate-y-24 del estado oculto el rect
 *  saldria de la zona y el estado oscilaria. */
function fabCoversInteractive(fab: HTMLElement): boolean {
    const styles = getComputedStyle(fab);
    const bottom = parseFloat(styles.bottom) || 0;
    const right = parseFloat(styles.right) || 0;
    const width = parseFloat(styles.width) || 0;
    const height = parseFloat(styles.height) || 0;
    if (!width || !height) return false;
    const zoneLeft = window.innerWidth - right - width;
    const zoneTop = window.innerHeight - bottom - height;
    const inset = 6;
    const points: [number, number][] = [
        [zoneLeft + width / 2, zoneTop + height / 2],
        [zoneLeft + inset, zoneTop + inset],
        [zoneLeft + width - inset, zoneTop + inset],
        [zoneLeft + inset, zoneTop + height - inset],
        [zoneLeft + width - inset, zoneTop + height - inset],
    ];
    return points.some(([x, y]) =>
        document.elementsFromPoint(x, y).some((el) => {
            if (el === fab || fab.contains(el)) return false;
            const control = el.closest(FAB_INTERACTIVE_SELECTOR);
            return control !== null && control !== fab && !fab.contains(control);
        }),
    );
}

export function GlobalBrain({ userId }: GlobalBrainProps) {
    const pathname = usePathname();
    const page = brainPageContext(pathname);
    const [isOpen, setIsOpen] = useState(false);
    const [isMaximized, setIsMaximized] = useState(false);
    const [echo, setEcho] = useState<ContextEcho | null>(null);
    const [messages, setMessages] = useState<Message[]>([
        { role: 'assistant', content: '¡Hola! Soy el cerebro de GerarAI. Pregúntame sobre tu cartera, tus tesis de inversión o lo que estés viendo.' }
    ]);
    const [input, setInput] = useState('');
    const [loading, setLoading] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    // La pastilla "Viendo X": el eco del servidor manda sobre la etiqueta local.
    const viewing = echo?.label ?? page?.label ?? null;

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
        }
    }, [messages, isOpen, isMaximized]);

    // Al cambiar de página el eco viejo deja de ser válido: vuelve la etiqueta local.
    useEffect(() => {
        setEcho(null);
    }, [pathname]);

    /**
     * Modal de verdad (WCAG 2.1.2): con `aria-modal` el fondo se marca inaccesible
     * para el lector de pantalla, el foco entra por el campo de mensaje y Escape
     * cierra sin enviar nada. El listener va en `document` porque el panel no
     * recibe el foco por si solo.
     */
    useEffect(() => {
        if (!isOpen) return;
        inputRef.current?.focus();

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            setIsOpen(false);
        };
        document.addEventListener('keydown', onKeyDown);
        return () => document.removeEventListener('keydown', onKeyDown);
    }, [isOpen]);

    /**
     * F339: a <md la burbuja fija (bottom-right) tapa la columna de porcentajes
     * de la leyenda del donut de Distribución EN REPOSO: el solape importa con
     * el scroll parado, no solo en movimiento. La burbuja se oculta (a) durante
     * el scroll, reapareciendo ~600 ms tras parar, y (b) siempre que la leyenda
     * intersecte su zona — incluido el reposo — hasta que deje de intersectarla.
     * En desktop (md+) las clases md:* la mantienen siempre visible.
     *
     * La zona se mide desde el computed style del propio botón (bottom/right
     * resuelven el env(safe-area-inset-*) de iPhone a px, y width/height dan el
     * tamaño real) y no desde getBoundingClientRect: al ocultarse con
     * translate-y-24 el rect saldría de la zona y la burbuja oscilaría. El
     * chequeo corre al montar, en scroll, en resize y ante un MutationObserver
     * acotado: las tabs de la cartera montan y desmontan la leyenda sin scroll
     * ni resize, y el estado no puede quedar obsoleto tras un cambio de tab.
     * La leyenda se re-consulta por id en cada chequeo y todo se limpia al
     * desmontar.
     */
    const [fabScrollHidden, setFabScrollHidden] = useState(false);
    const [fabLegendBlocked, setFabLegendBlocked] = useState(false);
    const [fabControlsBlocked, setFabControlsBlocked] = useState(false);
    const fabRef = useRef<HTMLButtonElement>(null);
    useEffect(() => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const checkLegendOverlap = () => {
            const legend = document.getElementById('portfolio-allocation-legend');
            const fab = fabRef.current;
            // FAB-390: en reposo el FAB tampoco puede tapar CONTROLES del borde
            // derecho en móvil (un botón o enlace bajo la burbuja no se puede
            // pulsar). Con o sin leyenda: se oculta hasta que dejan de cruzar
            // su zona. En md+ las clases md:* lo mantienen siempre visible.
            setFabControlsBlocked(fab ? fabCoversInteractive(fab) : false);
            if (!legend || !fab) {
                setFabLegendBlocked(false);
                return;
            }
            const styles = getComputedStyle(fab);
            const bottom = parseFloat(styles.bottom) || 0;
            const right = parseFloat(styles.right) || 0;
            const width = parseFloat(styles.width) || 0;
            const height = parseFloat(styles.height) || 0;
            const zoneLeft = window.innerWidth - right - width - 8;
            const zoneTop = window.innerHeight - bottom - height - 8;
            const rect = legend.getBoundingClientRect();
            setFabLegendBlocked(
                rect.right > zoneLeft && rect.left < window.innerWidth - right + 8 &&
                rect.bottom > zoneTop && rect.top < window.innerHeight - bottom + 8
            );
        };
        const onScroll = () => {
            setFabScrollHidden(true);
            if (timer !== undefined) clearTimeout(timer);
            timer = setTimeout(() => {
                setFabScrollHidden(false);
                checkLegendOverlap();
            }, 600);
            checkLegendOverlap();
        };
        checkLegendOverlap();
        const observer = new MutationObserver(checkLegendOverlap);
        observer.observe(document.body, { childList: true, subtree: true });
        window.addEventListener('scroll', onScroll, { passive: true, capture: true });
        window.addEventListener('resize', checkLegendOverlap, { passive: true });
        return () => {
            observer.disconnect();
            window.removeEventListener('scroll', onScroll, { capture: true });
            window.removeEventListener('resize', checkLegendOverlap);
            if (timer !== undefined) clearTimeout(timer);
        };
    }, []);
    const fabHidden = fabScrollHidden || fabLegendBlocked || fabControlsBlocked;

    async function handleSend() {
        if (!input.trim() || loading) return;

        const userMsg = input.trim();
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setInput('');
        setLoading(true);

        try {
            const result = await chatWithPortfolio(userMsg, userId, page);
            if (result.context) setEcho(result.context);
            if (result.success) {
                setMessages(prev => [...prev, { role: 'assistant', content: result.message, citations: result.citations }]);
            } else {
                setMessages(prev => [...prev, { role: 'assistant', content: result.message || "Lo siento, hubo un error desconocido." }]);
            }
        } catch {
            setMessages(prev => [...prev, { role: 'assistant', content: "No se pudo completar la respuesta. Si tarda más de lo normal, reinténtalo en unos segundos." }]);
        } finally {
            setLoading(false);
        }
    }

    // Burbuja fija: en móvil queda POR ENCIMA de la BottomNav (min-h-14 +
    // safe-area), nunca la tapa; en escritorio vuelve a la esquina habitual.
    if (!isOpen) {
        return (
            <Button
                ref={fabRef}
                onClick={() => setIsOpen(true)}
                aria-label="Abrir el cerebro"
                // `viewportFit: "cover"` + barra de inicio de iOS: sin el inset la
                // burbuja queda bajo la barra en modo standalone.
                className={`fixed bottom-[calc(4.75rem+env(safe-area-inset-bottom))] md:bottom-[calc(1.5rem+env(safe-area-inset-bottom))] right-[calc(1.5rem+env(safe-area-inset-right))] h-14 w-14 p-0 rounded-none shadow-none bg-transparent hover:bg-transparent text-white z-50 animate-in zoom-in duration-300 transition-all ${fabHidden ? 'translate-y-24 opacity-0 pointer-events-none md:translate-y-0 md:opacity-100 md:pointer-events-auto' : ''}`}
            >
                <BrainGlassesIcon className="h-14 w-14 shrink-0 object-contain" />
            </Button>
        );
    }

    // Panel: lateral derecho a toda altura en escritorio; hoja sobre la
    // BottomNav en móvil.
    return (
        <Card
            role="dialog"
            aria-modal="true"
            aria-labelledby="global-brain-title"
            aria-busy={loading}
            className={`fixed z-50 flex flex-col border-indigo-500/30 bg-slate-950/95 backdrop-blur-md shadow-2xl transition-all duration-300 ${isMaximized
            ? 'top-4 bottom-4 left-4 right-4 w-auto h-auto'
            : 'inset-x-2 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] top-20 md:inset-x-auto md:top-0 md:bottom-0 md:right-0 md:w-[420px] md:h-dvh md:rounded-none md:border-y-0 md:border-r-0'
            }`}
        >
            <CardHeader className="p-4 border-b border-indigo-500/20 flex flex-row items-center justify-between bg-indigo-900/20">
                <div className="flex min-w-0 items-center gap-2">
                    <BrainGlassesIcon className="h-9 w-9 shrink-0 object-contain" />
                    <CardTitle id="global-brain-title" className="text-sm font-medium">Cerebro GerarAI</CardTitle>
                    {viewing && (
                        <span
                            data-testid="brain-page-context"
                            title={echo?.company_name ?? undefined}
                            className="max-w-32 truncate rounded-full border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300"
                        >
                            Viendo {viewing}
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setIsMaximized(!isMaximized)}
                        aria-label={isMaximized ? 'Restaurar el cerebro' : 'Maximizar el cerebro'}
                        className="h-6 w-6 text-slate-400 hover:text-white"
                    >
                        {isMaximized ? <Minimize2 aria-hidden="true" className="h-4 w-4" /> : <Maximize2 aria-hidden="true" className="h-4 w-4" />}
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setIsOpen(false)}
                        aria-label="Cerrar el cerebro"
                        className="h-6 w-6 text-slate-400 hover:text-white"
                    >
                        <X aria-hidden="true" className="h-4 w-4" />
                    </Button>
                </div>
            </CardHeader>

            <CardContent className="flex-1 p-0 overflow-hidden relative">
                <div
                    ref={scrollRef}
                    role="log"
                    aria-live="polite"
                    aria-relevant="additions text"
                    aria-label="Mensajes del cerebro"
                    className="h-full overflow-y-auto p-4 space-y-4"
                >
                    {messages.map((m, i) => (
                        <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                            <div className={`flex items-start gap-2 max-w-[90%] ${m.role === 'user' ? 'flex-row-reverse' : ''}`}>
                                <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${m.role === 'user' ? 'bg-blue-600' : 'bg-indigo-600'}`}>
                                    {m.role === 'user' ? <User aria-hidden="true" className="h-3 w-3 text-white" /> : <Bot aria-hidden="true" className="h-3 w-3 text-white" />}
                                </div>
                                <div className={`p-3 rounded-lg text-sm overflow-hidden ${m.role === 'user'
                                    ? 'bg-blue-600 text-white rounded-tr-none'
                                    : 'bg-slate-800 text-slate-200 border border-slate-700 rounded-tl-none'
                                    }`}>
                                    {m.role === 'assistant' ? (
                                        <div className="prose prose-invert prose-sm max-w-none [&>h3]:text-indigo-400 [&>h3]:font-bold [&>h3]:mt-2 [&>h3]:mb-1 [&>ul]:list-disc [&>ul]:pl-4 [&>strong]:text-white">
                                            <ReactMarkdown
                                                components={{
                                                    h3: ({ node, ...props }) => <h3 className="text-base font-bold text-indigo-300 mt-2 mb-1" {...props} />,
                                                    ul: ({ node, ...props }) => <ul className="list-disc pl-4 space-y-1" {...props} />,
                                                    li: ({ node, ...props }) => <li className="text-slate-300" {...props} />,
                                                    strong: ({ node, ...props }) => <strong className="font-semibold text-white bg-indigo-500/10 px-1 rounded" {...props} />
                                                }}
                                            >
                                                {m.content}
                                            </ReactMarkdown>
                                            <BrainSources citations={m.citations} />
                                        </div>
                                    ) : (
                                        m.content
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                    {loading && (
                        <div className="flex justify-start">
                            <div className="flex items-start gap-2 max-w-[80%]">
                                <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                                    <Bot aria-hidden="true" className="h-3 w-3 text-white" />
                                </div>
                                <div role="status" aria-live="polite" className="p-3 rounded-lg bg-slate-800 border border-slate-700 rounded-tl-none">
                                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin text-indigo-400" />
                                    <span className="sr-only">GerarAI está escribiendo la respuesta.</span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </CardContent>

            <CardFooter className="p-3 border-t border-slate-800 bg-slate-900/50">
                <form
                    className="flex w-full gap-2"
                    onSubmit={(e) => { e.preventDefault(); handleSend(); }}
                >
                    <label htmlFor="global-brain-input" className="sr-only">
                        Pregunta al cerebro
                    </label>
                    <Input
                        ref={inputRef}
                        id="global-brain-input"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        placeholder="Pregunta al cerebro..."
                        className="bg-slate-950 border-slate-700 focus-visible:ring-indigo-500"
                    />
                    <Button type="submit" size="icon" aria-label="Enviar pregunta" disabled={loading || !input.trim()} aria-busy={loading} className="bg-indigo-600 hover:bg-indigo-500">
                        <Send aria-hidden="true" className="h-4 w-4" />
                    </Button>
                </form>
            </CardFooter>
        </Card>
    );
}
