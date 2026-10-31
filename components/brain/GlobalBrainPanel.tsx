'use client';
import { TickerSearchInput } from '@/components/search/TickerSearchInput';

import { useState, useRef, useEffect } from 'react';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { X, Send, User, Bot, Loader2, Maximize2, Minimize2 } from 'lucide-react';
import { BrainGlassesIcon } from '@/components/brain/BrainGlassesIcon';
import { useT } from '@/lib/i18n/client';
import { BRAIN_SUGGESTED_QUESTIONS } from '@/lib/brain/conversation';
import { chatWithPortfolio } from '@/lib/actions/brain.actions';
import { askResearchAssistantAction } from '@/lib/research/assistant-actions';
import type { AssistantResponse } from '@/lib/research/assistant-contract';
import { brainHandoffContext, type OpenBrainDetail, type KnowledgeBrainContext } from '@/lib/brain/open-brain';
import { brainPageContext } from '@/lib/brain/page-context';
import { BrainGuideAnswer } from './BrainGuideAnswer';
import dynamic from 'next/dynamic';

// react-markdown (con micromark/mdast, ~110 kB sin comprimir) solo hace falta
// cuando el Cerebro pinta una respuesta. Importado estático viajaba en el
// layout autenticado, es decir, en la carga inicial de TODAS las páginas,
// aunque el panel esté cerrado. Se carga al abrir el panel (ver efecto abajo).
const ReactMarkdown = dynamic(() => import('react-markdown'), {
    loading: () => <span className="block h-4 w-2/3 animate-pulse rounded bg-slate-700/60" aria-hidden="true" />,
});
import type { PortfolioChatCitation } from '@/lib/chat/citations';
import { BrainSources } from './BrainSources';
import { askKnowledgeResult, type LibraryAnswer } from '@/lib/actions/knowledge-chat.actions';
import { analysisToText, isSubmitShortcut, SUGGESTED_QUESTIONS } from '@/lib/knowledge/analysis';
const BrainLibraryAnswer = dynamic(() => import('./BrainLibraryAnswer').then(m => m.BrainLibraryAnswer));

export interface BrainMessage {
    role: 'user' | 'assistant';
    content: string;
    citations?: PortfolioChatCitation[];
    guide?: AssistantResponse;
    library?: LibraryAnswer;
}

export interface GlobalBrainPanelProps {
    userId: string;
    knowledge: KnowledgeBrainContext | null;
    /** Handoff de apertura (evento gerarai:open-brain o sessionStorage): el
        shell lo recibe siempre montado y lo pasa con un contador para que el
        panel lo aplique aunque llegue con el panel ya abierto. */
    openDetail: { detail: OpenBrainDetail | null; seq: number } | null;
    messages: BrainMessage[];
    setMessages: React.Dispatch<React.SetStateAction<BrainMessage[]>>;
    onClose: () => void;
    onClearKnowledge: () => void;
}

type ContextEcho = {
    label: string;
    ticker: string | null;
    company_name: string | null;
    company_resolved: boolean;
};

/**
 * Panel del cerebro global: chunk diferido que GlobalBrain (shell siempre
 * montado en el layout) carga al abrirlo. Panel lateral en escritorio, hoja
 * sobre la BottomNav en móvil; en la biblioteca y las cartas, el mismo panel
 * flotante con el contexto de doctrina de la página.
 * Cada pregunta lleva el contexto de página explícito (pastilla "Viendo X");
 * el eco que devuelve el servidor (IDs resueltos y permisos aplicados allí)
 * manda sobre la etiqueta local. Solo lectura.
 */
export function GlobalBrainPanel({ userId, knowledge, openDetail, messages, setMessages, onClose, onClearKnowledge }: GlobalBrainPanelProps) {
    const t = useT();
    const pathname = usePathname();
    const page = brainPageContext(pathname);
    // El panel solo se monta al abrirlo (chunk diferido desde GlobalBrain):
    // precarga el renderizador de markdown nada más montar, antes de que
    // llegue la primera respuesta, para que no se note la carga diferida.
    useEffect(() => {
        void import('react-markdown');
    }, []);
    const [isMaximized, setIsMaximized] = useState(false);
    // Modo guía (asistente de research unificado): con ticker en el selector el
    // Cerebro pregunta a /api/research/assistant en vez de al chat general.
    const [author, setAuthor] = useState('');
    const [analysis, setAnalysis] = useState(false);
    // El handoff vigente al montar se aplica en el estado inicial (el shell ya
    // lo tenía cuando pidió el chunk): el panel no abre con el input vacío un
    // tick antes de enseñar la pregunta precargada. Handoffs posteriores con
    // el panel ya abierto los aplica el efecto de más abajo (por seq).
    const initialHandoff = openDetail ? brainHandoffContext(openDetail.detail) : null;
    const [guideTicker, setGuideTicker] = useState(initialHandoff?.ticker ?? '');
    // El selector de ticker de la guía queda plegado tras un botón: un input
    // suelto en la cabecera parecía herramienta de desarrollo. Con ticker
    // activo (o al abrirlo) se muestra siempre.
    const [showGuideInput, setShowGuideInput] = useState(false);
    const [reviewId, setReviewId] = useState<number | undefined>(initialHandoff?.reviewId);

    const [echo, setEcho] = useState<ContextEcho | null>(null);
    const [input, setInput] = useState(() => openDetail?.detail?.question?.slice(0, 2000) ?? '');
    const [loading, setLoading] = useState(false);
    const [copied, setCopied] = useState<number | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
    const dialogRef = useRef<HTMLDivElement>(null);
    const previousFocusRef = useRef<HTMLElement | null>(null);
    // Handoffs de apertura: el shell (GlobalBrain) los recibe siempre montado
    // y pasa el detalle con un contador; cada apertura sustituye el anclaje
    // anterior, incluso sin review_id.
    const appliedSeqRef = useRef(openDetail?.seq ?? 0);
    useEffect(() => {
        if (!openDetail || openDetail.seq === appliedSeqRef.current) return;
        appliedSeqRef.current = openDetail.seq;
        const context = brainHandoffContext(openDetail.detail);
        setAuthor('');
        setAnalysis(false);
        setGuideTicker(context.ticker);
        setReviewId(context.reviewId);
        if (openDetail.detail?.question) setInput(openDetail.detail.question.slice(0, 2000));
    }, [openDetail]);

    async function copyMessage(index: number, content: string) {
        try {
            await navigator.clipboard.writeText(content);
            setCopied(index);
        } catch {
            setCopied(null);
        }
    }

    // Al cambiar el contexto de conocimiento (página de biblioteca o handoff) el
    // modo guía se reinicia: es lo que hacía el shell antes del split. Ajuste
    // durante el render (reset al cambiar un valor), no efecto.
    const [previousKnowledge, setPreviousKnowledge] = useState(knowledge);
    if (previousKnowledge !== knowledge) {
        setPreviousKnowledge(knowledge);
        setGuideTicker('');
        setReviewId(undefined);
        setAuthor('');
        setAnalysis(false);
    }

    // La pastilla "Viendo X": el eco del servidor manda sobre la etiqueta local.
    const viewing = knowledge?.documentTitle ?? echo?.label ?? page?.label ?? null;
    // Y la pastilla NAVEGA: si el eco resolvió un ticker va a su ficha; si no,
    // a la página que el cliente está viendo (la pastilla deja de ser texto muerto).
    const viewingHref = echo?.ticker
        ? `/research/${encodeURIComponent(echo.ticker)}`
        : page?.path ?? null;

    useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
        }
    }, [messages, isMaximized]);

    // Al cambiar de página el eco viejo deja de ser válido: vuelve la etiqueta
    // local. Ajuste durante el render (reset al cambiar un valor), no efecto.
    const [prevPathname, setPrevPathname] = useState(pathname);
    if (prevPathname !== pathname) {
        setPrevPathname(pathname);
        setEcho(null);
    }

    /**
     * Modal de verdad (WCAG 2.1.2): con `aria-modal` el fondo se marca inaccesible
     * para el lector de pantalla, el foco entra por el campo de mensaje, Tab y
     * Shift+Tab circulan solo por el panel y Escape cierra sin enviar nada. El
     * resto del arbol queda `inert` + `aria-hidden` mientras dura el dialogo (el
     * mismo patron de components/MobileNav.tsx) y el foco vuelve a quien lo abrio
     * al cerrar. El listener va en `document` porque el panel no recibe el foco
     * por si solo.
     */
    useEffect(() => {
        const dialog = dialogRef.current;
        if (!dialog) return;

        previousFocusRef.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        inputRef.current?.focus();

        // Hermanos del panel hacia arriba: todo lo que no es el propio panel ni
        // sus ancestros deja de ser alcanzable por teclado/lector. Se guardan
        // los valores previos para no pisar `inert`/`aria-hidden` ajenos.
        const hidden: Array<{ element: HTMLElement; inert: boolean; ariaHidden: string | null }> = [];
        let node: HTMLElement | null = dialog;
        while (node && node !== document.body && node.parentElement) {
            const parent: HTMLElement = node.parentElement;
            for (const sibling of Array.from(parent.children)) {
                if (sibling === node || !(sibling instanceof HTMLElement)) continue;
                if (['SCRIPT', 'STYLE', 'LINK', 'TEMPLATE'].includes(sibling.tagName)) continue;
                hidden.push({
                    element: sibling,
                    inert: sibling.inert,
                    ariaHidden: sibling.getAttribute('aria-hidden'),
                });
                sibling.inert = true;
                sibling.setAttribute('aria-hidden', 'true');
            }
            node = parent;
        }

        const previousOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';

        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onClose();
                return;
            }
            if (event.key !== 'Tab') return;
            const activeDialog = dialogRef.current;
            if (!activeDialog) return;
            // Mismo filtro que MobileNav: fuera los focusables invisibles por
            // breakpoint y los que no son tab stops reales.
            const focusable = Array.from(
                activeDialog.querySelectorAll<HTMLElement>(
                    'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
                ),
            ).filter((el) => el.tabIndex >= 0 && el.getClientRects().length > 0);
            if (focusable.length === 0) {
                event.preventDefault();
                activeDialog.focus();
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            // El panel (tabIndex=-1) y el body no estan en el ciclo: sin esto,
            // Shift+Tab desde ahi salia al chrome del navegador.
            if (document.activeElement === activeDialog || document.activeElement === document.body) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
                return;
            }
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        };
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('keydown', onKeyDown);
            document.body.style.overflow = previousOverflow;
            for (const item of hidden) {
                item.element.inert = item.inert;
                if (item.ariaHidden === null) item.element.removeAttribute('aria-hidden');
                else item.element.setAttribute('aria-hidden', item.ariaHidden);
            }
            const previous = previousFocusRef.current;
            if (previous && previous.isConnected && previous.getClientRects().length > 0) previous.focus();
            else (document.activeElement as HTMLElement | null)?.blur?.();
        };
    }, []);

    async function handleSend() {
        if (!input.trim() || loading) return;

        const userMsg = input.trim();
        const history = messages.map(({ role, content }) => ({ role, content }));
        setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
        setInput('');
        setLoading(true);

        if (knowledge) {
            try {
                const outcome = await askKnowledgeResult(userMsg, knowledge.scope, author, analysis ? 'analisis' : 'respuesta', page, knowledge.documentId);
                if (!outcome.ok) {
                    setMessages(prev => [...prev, { role: 'assistant', content: outcome.message }]);
                    return;
                }
                const result = outcome.answer;
                const text = result.analysis ? analysisToText(result.analysis) : (result.answers ?? []).map(a => `${a.text ?? ''}\n«${a.citation.quote}» (${a.citation.author ?? t('brain.library.unregisteredAuthor')} · ${a.citation.title}${a.citation.page_number !== null ? ` · ${t('brain.library.pageN', { n: a.citation.page_number })}` : ''} · ${t('brain.library.chunkN', { n: a.citation.chunk_index + 1 })}${a.citation.publication_date ? ` · ${a.citation.publication_date}` : ''})`).join('\n\n');
                setMessages(prev => [...prev, { role: 'assistant', content: text || result.message || t('brain.panel.noLibraryData'), library: result }]);
            } catch (error) {
                const expired = typeof error === 'object' && error !== null && 'statusCode' in error && error.statusCode === 401;
                const message = expired ? t('brain.panel.sessionExpired') : error instanceof Error && /sesión|sesi[oó]n|401/i.test(error.message) ? error.message : t('brain.panel.libraryError');
                setMessages(prev => [...prev, { role: 'assistant', content: message }]);
            } finally { setLoading(false); }
            return;
        }
        const cleanTicker = guideTicker.trim().toUpperCase();
        if (cleanTicker) {
            // Modo guía: asistente de research (solo lectura), secciones y citas tipadas.
            if (userMsg.length < 3 || userMsg.length > 2000) {
                setMessages(prev => [...prev, { role: 'assistant', content: t('brain.panel.questionLength') }]);
                setLoading(false);
                return;
            }
            try {
                const result = await askResearchAssistantAction({
                    mode: 'guide',
                    question: userMsg,
                    ticker: cleanTicker,
                    ...(reviewId ? { review_id: reviewId } : {}),
                    page,
                    history,
                });
                if (result.context) setEcho(result.context);
                setMessages(prev => [...prev, {
                    role: 'assistant',
                    content: result.answer?.trim() ? result.answer : t('brain.panel.guideEmpty', { ticker: cleanTicker }),
                    guide: result,
                }]);
            } catch {
                setMessages(prev => [...prev, { role: 'assistant', content: t('brain.panel.guideError') }]);
            } finally {
                setLoading(false);
            }
            return;
        }
        try {
            const result = await chatWithPortfolio(userMsg, userId, page, history);
            if (result.context) setEcho(result.context);
            if (result.success) {
                setMessages(prev => [...prev, { role: 'assistant', content: result.message, citations: result.citations }]);
            } else {
                setMessages(prev => [...prev, { role: 'assistant', content: result.message || t('brain.panel.unknownError') }]);
            }
        } catch {
            setMessages(prev => [...prev, { role: 'assistant', content: t('brain.panel.responseError') }]);
        } finally {
            setLoading(false);
        }
    }

    // Panel: lateral derecho a toda altura en escritorio; hoja sobre la
    // BottomNav en móvil.
    const panel = (
        <Card
            ref={dialogRef}
            tabIndex={-1}
            role="dialog"
            aria-modal
            aria-labelledby="global-brain-title"
            aria-busy={loading}
            className={`fixed z-50 flex flex-col border-indigo-500/30 shadow-2xl transition-all duration-300 ${isMaximized
            ? // Maximizado el panel cubre casi toda la pantalla: fondo sólido,
              // sin transparencia; con /95 la barra inferior se veía detrás
              // del campo de texto (informe UX 29-oct, punto 9).
              'top-4 bottom-4 left-4 right-4 w-auto h-auto bg-slate-950'
            : 'inset-x-2 bottom-[calc(7rem+env(safe-area-inset-bottom))] top-20 bg-slate-950/95 backdrop-blur-md md:inset-x-auto md:top-0 md:bottom-0 md:right-0 md:w-[420px] md:h-dvh md:rounded-none md:border-y-0 md:border-r-0'
            }`}
        >
            <CardHeader className="shrink-0 p-4 border-b border-indigo-500/20 flex flex-row items-center justify-between bg-indigo-900/20">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <BrainGlassesIcon className="h-9 w-9 shrink-0 object-contain" />
                    <CardTitle as="h2" id="global-brain-title" className="text-sm font-medium">{t('brain.panel.title')}</CardTitle>
                    {showGuideInput || guideTicker ? (
                        <TickerSearchInput
                            value={guideTicker}
                            onValueChange={(value) => { onClearKnowledge(); setGuideTicker(value); setReviewId(undefined); }}
                            onSelect={(stock) => { onClearKnowledge(); setGuideTicker(stock.symbol); setReviewId(undefined); }}
                            onBlur={() => { if (!guideTicker.trim()) setShowGuideInput(false); }}
                            placeholder={t('brain.panel.tickerPlaceholder')}
                            ariaLabel={t('brain.panel.tickerAria')}
                            className="w-full min-w-0 rounded-full border border-slate-700 bg-slate-900 px-2 text-slate-200"
                        />
                    ) : (
                        <button
                            type="button"
                            onClick={() => { onClearKnowledge(); setShowGuideInput(true); }}
                            title={t('brain.panel.guideButtonTitle')}
                            aria-label={t('brain.panel.guideButtonAria')}
                            className="inline-flex min-h-11 items-center rounded-full border border-slate-700 bg-slate-900 px-2 py-0.5 text-xs text-slate-400 hover:border-indigo-400 hover:text-slate-200"
                        >
                            {t('brain.panel.guideButton')}
                        </button>
                    )}
                    {reviewId ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300">
                            {t('brain.panel.review', { id: reviewId })}
                            <button type="button" aria-label={t('brain.panel.removeReviewAria')} onClick={() => setReviewId(undefined)} className="inline-flex min-h-11 min-w-11 items-center justify-center text-indigo-400 hover:text-indigo-200 sm:min-h-0 sm:min-w-0">×</button>
                        </span>
                    ) : null}
                    {viewing && (
                        viewingHref ? (
                            <Link
                                href={viewingHref}
                                data-testid="brain-page-context"
                                title={echo?.company_name ?? undefined}
                                className="inline-flex min-h-11 items-center max-w-32 truncate rounded-full border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300 hover:border-indigo-400 hover:text-indigo-200"
                            >
                                {t('brain.panel.viewing', { label: viewing })}
                            </Link>
                        ) : (
                            <span
                                data-testid="brain-page-context"
                                title={echo?.company_name ?? undefined}
                                className="max-w-32 truncate rounded-full border border-indigo-500/40 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-300"
                            >
                                {t('brain.panel.viewing', { label: viewing })}
                            </span>
                        )
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setIsMaximized(!isMaximized)}
                        aria-label={isMaximized ? t('brain.panel.restoreAria') : t('brain.panel.maximizeAria')}
                        className="size-11 text-slate-400 hover:text-white"
                    >
                        {isMaximized ? <Minimize2 aria-hidden="true" className="h-4 w-4" /> : <Maximize2 aria-hidden="true" className="h-4 w-4" />}
                    </Button>
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => onClose()}
                        aria-label={t('brain.panel.closeAria')}
                        className="size-11 text-slate-400 hover:text-white"
                    >
                        <X aria-hidden="true" className="h-4 w-4" />
                    </Button>
                </div>
            </CardHeader>

            {knowledge && <div className="shrink-0 flex flex-col gap-2 border-b border-slate-700 p-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2"><span>{knowledge.documentTitle ? t('brain.panel.letterPrefix', { title: knowledge.documentTitle }) : knowledge.scope === 'letters' ? t('brain.panel.letters') : t('brain.panel.library')} · {t('brain.panel.doctrineNote')}</span><button type="button" className="min-h-11 text-indigo-300" onClick={() => onClearKnowledge()}>{t('brain.panel.backToChat')}</button></div>
                <details><summary className="min-h-11 cursor-pointer py-2">{t('brain.panel.authorAnalysis')}</summary>
                {!!knowledge.authors?.length && <label>{t('brain.panel.authorLabel')}<select aria-label={t('brain.panel.authorLabel')} value={author} onChange={e => setAuthor(e.target.value)} className="block min-h-11 w-full rounded bg-slate-900 p-2"><option value="">{t('brain.panel.allAuthors')}</option>{knowledge.authors.map(a => <option key={a} value={a}>{a}</option>)}</select></label>}
                <label className="flex min-h-11 items-center gap-2"><input type="checkbox" checked={analysis} onChange={e => setAnalysis(e.target.checked)} />{t('brain.panel.structuredAnalysis')}</label></details>
            </div>}
            <CardContent className="min-h-0 flex-1 p-0 overflow-hidden relative">
                <div
                    ref={scrollRef}
                    role="log"
                    aria-live="polite"
                    aria-relevant="additions text"
                    aria-label={t('brain.panel.messagesAria')}
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
                                    {m.role === 'assistant' && m.library ? (
                                        <BrainLibraryAnswer result={m.library} />
                                    ) : m.role === 'assistant' && m.guide ? (
                                        <BrainGuideAnswer result={m.guide} />
                                    ) : m.role === 'assistant' ? (
                                        <div className="prose prose-invert prose-sm max-w-none [&>h3]:text-indigo-400 [&>h3]:font-bold [&>h3]:mt-2 [&>h3]:mb-1 [&>ul]:list-disc [&>ul]:pl-4 [&>strong]:text-white">
                                            <ReactMarkdown
                                                components={{
                                                    h3: ({ node, ...props }) => <h3 className="text-base font-bold text-indigo-300 mt-2 mb-1" {...props} />,
                                                    ul: ({ node, ...props }) => <ul className="list-disc pl-4 space-y-1" {...props} />,
                                                    li: ({ node, ...props }) => <li className="text-slate-300" {...props} />,
                                                    strong: ({ node, ...props }) => <strong className="font-semibold text-white bg-indigo-500/10 px-1 rounded" {...props} />,
                                                    // Los enlaces de la respuesta son navegación real: las rutas
                                                    // internas (/research/ASTS, /portfolio…) abren con next/link
                                                    // sin recargar la app; las externas abren en pestaña nueva.
                                                    a: ({ node, href, children, ...props }) =>
                                                        href && href.startsWith('/') ? (
                                                            <Link href={href} className="text-indigo-300 underline underline-offset-2 hover:text-indigo-200">
                                                                {children}
                                                            </Link>
                                                        ) : (
                                                            <a href={href} target="_blank" rel="noopener noreferrer" className="text-indigo-300 underline underline-offset-2 hover:text-indigo-200" {...props}>
                                                                {children}
                                                            </a>
                                                        )
                                                }}
                                            >
                                                {m.content}
                                            </ReactMarkdown>
                                            <BrainSources citations={m.citations} />
                                        </div>
                                    ) : (
                                        m.content
                                    )}
                                    {m.role === 'assistant' && i > 0 && (
                                        <button
                                            type="button"
                                            onClick={() => void copyMessage(i, m.content)}
                                            className="mt-2 block min-h-11 text-xs text-indigo-300 hover:text-indigo-200"
                                        >
                                            {copied === i ? t('brain.panel.copied') : t('brain.panel.copy')}
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))}
                    {messages.length === 1 && !loading && (
                        <div className="flex flex-wrap gap-2" aria-label={t('brain.panel.suggestedAria')}>
                            {(knowledge ? SUGGESTED_QUESTIONS : BRAIN_SUGGESTED_QUESTIONS).map((text) => (
                                <button
                                    key={text}
                                    type="button"
                                    onClick={() => { setInput(text); inputRef.current?.focus(); }}
                                    className="inline-flex min-h-11 items-center rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-indigo-400 hover:text-indigo-200"
                                >
                                    {text}
                                </button>
                            ))}
                        </div>
                    )}
                    {loading && (
                        <div className="flex justify-start">
                            <div className="flex items-start gap-2 max-w-[80%]">
                                <div className="w-6 h-6 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
                                    <Bot aria-hidden="true" className="h-3 w-3 text-white" />
                                </div>
                                <div role="status" aria-live="polite" className="p-3 rounded-lg bg-slate-800 border border-slate-700 rounded-tl-none">
                                    <Loader2 aria-hidden="true" className="h-4 w-4 animate-spin text-indigo-400" />
                                    <span className="sr-only">{knowledge && analysis ? t('brain.panel.preparingAnalysis') : t('brain.panel.writing')}</span>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </CardContent>

            <CardFooter className="shrink-0 p-3 border-t border-slate-800 bg-slate-900/50">
                <form
                    className="flex w-full gap-2"
                    onSubmit={(e) => { e.preventDefault(); handleSend(); }}
                >
                    <label htmlFor="global-brain-input" className="sr-only">
                        {t('brain.panel.inputLabel')}
                    </label>
                    {knowledge ? <textarea
                        ref={inputRef as React.RefObject<HTMLTextAreaElement>}
                        id="global-brain-input"
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => { if (isSubmitShortcut(e)) { e.preventDefault(); void handleSend(); } }}
                        minLength={3} maxLength={1200} rows={2}
                        placeholder={t('brain.panel.libraryPlaceholder')}
                        className="min-h-11 min-w-0 flex-1 rounded border border-slate-700 bg-slate-950 p-2"
                    /> : <Input
                        ref={inputRef as React.RefObject<HTMLInputElement>}
                        id="global-brain-input"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        maxLength={2000}
                        placeholder={guideTicker.trim() ? t('brain.panel.tickerQuestion', { ticker: guideTicker.trim().toUpperCase() }) : t('brain.panel.placeholder')}
                        className="min-h-11 bg-slate-950 border-slate-700 focus-visible:ring-indigo-500"
                    />}
                    <Button type="submit" size="icon" aria-label={t('brain.panel.sendAria')} disabled={loading || !input.trim() || (!!knowledge && (input.trim().length < 3 || input.trim().length > 1200))} aria-busy={loading} className="bg-indigo-600 hover:bg-indigo-500">
                        <Send aria-hidden="true" className="h-4 w-4" />
                    </Button>
                </form>
            </CardFooter>
        </Card>
    );
    return panel;
}
