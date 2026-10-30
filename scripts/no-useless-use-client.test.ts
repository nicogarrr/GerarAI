/**
 * D2c: ningun 'use client' sin motivo.
 *
 * Por que un guard y no una nota en el README: cada 'use client' es un modulo
 * de JS que el navegador descarga, parsea y ejecuta para pintar algo que el
 * servidor ya sabe pintar. Cuando la directiva no esta justificada, ese JS es
 * gasto invisible, y a los tres meses ya nadie recuerda por que estaba. Un
 * guard lo convierte en un fallo de CI en vez de en una opinion.
 *
 * Que mira: un fichero de `components/` o `app/` con la directiva en el
 * prologo tiene que emitir AL MENOS una senal de cliente:
 *   - un hook de cliente (useState/useEffect/useReducer/useRef/useContext/
 *     useTransition/..., los de `next/navigation` y los de `react-dom`);
 *   - un event handler JSX (onClick, onChange, onSubmit, ...);
 *   - acceso a window/document/localStorage/navigator/...;
 *   - `dynamic(..., { ssr: false })`, `lazy` o `createContext`;
 *   - un paquete que solo funciona en cliente (@radix-ui/*, recharts, cmdk,
 *     sonner, react-hook-form, ...);
 *   - o importar un modulo que ya es cliente (sin la directiva, el import
 *     revienta).
 *
 * Lo que NO cuenta como motivo, y por eso hay una lista de excepciones: que
 * el fichero lo importe un Client Component. En ese caso sigue siendo cliente
 * por herencia, asi que quitar la directiva no ahorra un solo byte y solo
 * anade ruido al diff. Esa es la UNICA categoria con excepciones, y cada
 * entrada lleva escrito por que sigue asi.
 *
 * Ejecucion: node --experimental-strip-types --test scripts/no-useless-use-client.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { analyzeSource, auditRepo, auditUseClient } from './use-client-audit.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

/**
 * Excepciones de `components/`.
 *
 * Unico motivo admitido: el fichero lo importa un Client Component, asi que
 * ya es cliente por herencia y la directiva es redundante pero inocua. No se
 * tocan porque convertirlos no ahorra bytes: son hoja del subarbol cliente de
 * PortfolioTabs / ProPicksTabs / TaxesView.
 */
const COMPONENTS_EXCEPTIONS: Record<string, string> = {
  'components/portfolio/PortfolioScores.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'), asi que ya viaja en el paquete del cliente por herencia. Quitar la directiva NO ahorra un byte (sigue siendo cliente) y solo anade ruido al diff. Sin senal propia de cliente: solo pinta datos que recibe por props.",
  'components/portfolio/PortfolioSummary.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
  'components/portfolio/PortfolioTearsheet.tsx':
    "Lo importa components/portfolio/PortfolioTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
  'components/proPicks/StrategyFactsheet.tsx':
    "Lo importa components/proPicks/ProPicksTabs.tsx ('use client'): cliente por herencia, quitar la directiva no ahorra un byte. Se deja tal cual para no ensuciar el diff de un fichero sin ganancia real.",
};

/**
 * Excepciones de `app/`.
 *
 * Vacia a proposito: los ficheros de `app/` con la directiva
 * (error, global-error, ownership/SyncButton) la necesitan de
 * verdad (useState/useEffect/useTransition + handlers de submit), asi que el
 * mismo guard pasa sin excepciones. Se deja la lista declarada para que anadir
 * una excepcion aqui sea un acto explicito y no un descuido.
 */
const APP_EXCEPTIONS: Record<string, string> = {};

/**
 * Allowlist por ruta de las directivas 'use client' justificadas.
 *
 * Antes habia un contador total: dos PRs paralelas que anadiesen un fichero
 * cliente chocaban siempre en el numero, y el que mergeaba segundo dejaba
 * main en rojo. La lista por ruta mantiene el mismo rigor (un fichero
 * cliente nuevo NO listado falla; una entrada obsoleta falla) y las PRs
 * paralelas solo anaden lineas distintas.
 *
 * Alta de un fichero cliente nuevo: anade su ruta ordenada alfabeticamente
 * con el motivo (la senal de cliente que lo exige). El motivo se lee en la
 * revision; el guard exige que el fichero exista, siga teniendo la
 * directiva y el detector la siga justificando.
 */
const JUSTIFIED_USE_CLIENT: Record<string, string> = {
  'components/LoadingState.tsx': 'useT lee el contexto de locale para estados de carga accesibles',
  'components/ui/methodology-disclosure.tsx': 'useT lee locale para título predeterminado; también usado desde componentes client',
  'components/ui/name-avatar.tsx': 'useT lee locale para el texto alternativo de la foto',
  'components/proPicks/WalkForwardResults.tsx': 'importa MethodologyDisclosure client, que ahora consume contexto React de locale',

  'components/settings/LanguageForm.tsx':
    'selector de idioma: escribe la cookie de locale y router.refresh() (transición)',
  'lib/i18n/client.tsx':
    'provider y hooks de locale (useT/useLocale/useFormat): contexto React de cliente por definición',
  'components/research/ValuationSummaryGrid.tsx': 'useState y useEffect para carga batch asíncrona y descarte de respuestas de selección anterior',
  'components/alerts/PushNotifications.tsx': 'useState/useEffect para permiso Notification, registro serviceWorker, PushManager y preferencias opt-in del navegador',
  'components/research/ChangesFeed.tsx': 'useState y useMemo para filtros y paginación interactiva de sucesos',
  'components/research/AnalystTargetsView.tsx': 'useState para la paginación de firmas (5 por página) sin recargar la ficha',
  'components/research/DocumentsList.tsx': 'useState y useMemo, onChange para búsqueda y página actual',
  'components/research/ExpectationsList.tsx': 'useState para paginación de comparaciones y previsiones',
  'components/research/Pager.tsx': 'jsx-onClick para avanzar y retroceder páginas',
  'components/insider/PagedInsiderCompanies.tsx': 'useState para la página actual del paginador de empresas insider',
  'components/HomeAttention.tsx':
    'useEffect loads independent attention sources; useState controls retries and bounded pagination',
  'app/(root)/inversores/_components/LibraryChat.tsx':
    'onClick del botón compacto abre el Cerebro flotante (openBrain) con el contexto de la biblioteca; se importa desde páginas server',
  'components/research/DecisionJournalEntryLink.tsx':
    'Client boundary for onClick and browser hash scrolling via scrollToHashAnchor; imported from server CompanyNavigation.',
  'components/research/ResearchHashScroll.tsx':
    'useEffect + window (location.hash, hashchange) para el scroll al ancla al llegar a la ficha; montado desde la página server dentro de Suspense.',
    'components/proPicks/DeepValueView.tsx':
        'filtros controlados con useState/useEffect/useCallback y server actions al cambiar criterios',
    'components/proPicks/RadarGlobalView.tsx':
        'radar interactivo con useState y onClick que consulta candidatos mediante server action', 
    'components/pwa/ServiceWorkerRegister.tsx':
        'registro del service worker: useEffect + navigator.serviceWorker (API del navegador); sustituye al script inline del layout para la CSP con nonce',
    // Directivas reales que faltaban en la lista (QA 27-oct, fallo #20):
    'components/forms/InputField.tsx':
        'campo de formulario con useState (mostrar/ocultar contraseña), onClick y spread de props de react-hook-form',
    'components/portfolio/ImportImageButton.tsx':
        'diálogo de importación por captura: useState, useRef, FileReader del navegador, useRouter y toasts de sonner',
    'components/settings/IBKRConnectionForm.tsx':
        'formulario controlado de la conexión IBKR (useState, onSubmit, onChange)',
    'components/settings/SettingsSection.tsx':
        'useEffect con window/document para desplazar a la sección del ancla',
    'components/watchlist/WatchlistMembership.tsx':
        'contexto de pertenencia a la watchlist (createContext, useState, useContext) compartido por la página y los botones',
    'components/paper-trading/ManualDemoPanel.tsx':
        'tabs interactivas de la cuenta demo (estado de pestana en cliente)',
    'components/paper-trading/OrderTicket.tsx':
        'formulario controlado del ticket manual (estado, validacion y envio)',
    'components/paper-trading/FxTicket.tsx':
        'formulario controlado de la conversion de divisa manual',

  // selector de inversor y contenido con navegación por URL.
  'app/(root)/inversores/_components/InvestorSelector.tsx': 'useRouter, jsx-onChange',
  'app/(root)/inversores/_components/InvestorViewSelector.tsx': 'useRouter, jsx-onChange',

  'components/forms/SignInForm.tsx': 'useRouter, useState, jsx-onSubmit, jsx-onClick, libreria cliente: react-hook-form, libreria cliente: sonner',
  'app/(root)/error.tsx': 'useEffect, jsx-onClick',
  'components/settings/DcaAlertsForm.tsx': 'useState, jsx-onSubmit, jsx-onChange (ajustes globales DCA por tenant)',
  'components/watchlist/DcaAlertSettingsList.tsx': 'useState, jsx-onClick (paginación acotada de ajustes de aviso DCA)',
  'components/watchlist/LazyDcaControls.tsx': 'dynamic (frontera perezosa de las islas del panel DCA: DcaEvaluateButton, DcaHitRatesPopover)',
  'components/watchlist/DcaEvaluateButton.tsx': 'useState, useRouter, jsx-onClick',
  'components/watchlist/DcaHitRatesPopover.tsx': 'useState, useTransition, jsx-onClick',
  'components/watchlist/DcaLevelBadge.tsx': 'useState, useRef, jsx-onClick, jsx-onPointerDown, jsx-onOpenChange (el toque abre el detalle del nivel DCA en el móvil)',
  'components/proPicks/DcaBacktestPanel.tsx': 'useState, useTransition, jsx-onSubmit, jsx-onChange',
  'app/(root)/inversores/_components/HubNav.tsx': 'usePathname',
  'app/(root)/inversores/_components/IngestLettersButton.tsx': 'useState, jsx-onClick',
  'app/(root)/inversores/_components/SyncPortfoliosButton.tsx': 'useState, jsx-onClick',
  'app/(root)/ownership/SyncButton.tsx': 'useTransition, useState, jsx-onClick',
  'app/(root)/temas/_components/ThemeBrainButton.tsx': 'jsx-onClick, browser:window',
  'app/(root)/temas/_components/ThemeOrderToggle.tsx': 'next-navigation:useRouter',
  'app/global-error.tsx': 'jsx-onClick',
  'components/ErrorBoundary.tsx': 'jsx-onClick, browser:window, jsx-spread',
  'components/GlossaryTerm.tsx': 'importa cliente: components/ui/tooltip.tsx',
  'components/MobileNav.tsx': 'useState, useRef, jsx-onClick, jsx-onPointerDown, jsx-onFocus, dynamic (drawer diferido en MobileNavDrawer)',
  'components/MobileNavDrawer.tsx': 'useRef, useEffect, browser:HTMLElement, browser:document, browser:window, jsx-onClick, react-dom:createPortal, importa cliente: components/NavItems.tsx, importa cliente: components/SearchCommand.tsx (chunk diferido: solo se descarga al abrir el menú)',
  'components/NavItems.tsx': 'usePathname',
  'components/OnlineBanner.tsx': 'jsx-spread, importa cliente: hooks/useOnlineStatus.ts',
  'components/PersonalizedOverview.tsx': 'jsx-onClick, useState, useEffect, jsx-onRetry',
  'components/PublicMobileNav.tsx': 'useState, useRef, useEffect, browser:HTMLElement, browser:document, browser:window, jsx-onClick',
  'components/SearchCommand.tsx': 'useRef, browser:HTMLElement, browser:document, useEffect, browser:window, jsx-onClick, jsx-onPointerDown, jsx-onFocus, dynamic (paleta cmdk diferida en SearchCommandDialog)',
  'components/SearchCommandDialog.tsx': 'useRouter, useState, useRef, useEffect, jsx-onOpenChange, jsx-onCloseAutoFocus, jsx-onValueChange, jsx-onSelect, jsx-onMouseEnter, importa cliente: components/ui/command.tsx (chunk diferido: solo se descarga al abrir el buscador)',
  'components/settings/BaseCurrencyForm.tsx': 'useState para la divisa seleccionada y el estado de guardado; onValueChange y onClick para cambiar y persistir la divisa base',
  'components/search/TickerSearchInput.tsx': 'useState, useCallback, useRef, useEffect, browser:fetch, jsx-onChange, jsx-onClick',
  'components/UserDropdown.tsx': 'useRouter, jsx-onClick, importa cliente: components/ui/dropdown-menu.tsx, importa cliente: components/ui/avatar.tsx',
  'components/alerts/AlertsManager.tsx': 'useSearchParams, useState, useEffect, jsx-onOpenChange, jsx-onChange, jsx-onValueChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/confirm-dialog.tsx, importa cliente: components/ui/dialog.tsx, importa cliente: components/ui/select.tsx, importa cliente: components/ui/label.tsx',
  'components/brain/GlobalBrain.tsx': 'usePathname, useState, useEffect, browser:window, jsx-onClick, jsx-onPointerDown, jsx-onFocus, dynamic (panel del cerebro diferido en GlobalBrainPanel)',
  'components/brain/GlobalBrainPanel.tsx': 'usePathname, useState, useRef, useEffect, browser:navigator, browser:document, jsx-onClick, jsx-spread, jsx-onSubmit, jsx-onChange, dynamic react-markdown (chunk diferido: solo se descarga al abrir el cerebro)',
  'components/calendar/CompanyLogo.tsx': 'useState: cae al mosaico de iniciales cuando la imagen del ticker da 404',
  'components/calendar/CalendarTabs.tsx': 'usePathname',
  'components/calendar/SubscriptionManager.tsx': 'useState, jsx-onClick, jsx-onFocus, browser:navigator, useTransition',
  'components/corporate-actions/CorporateActionsView.tsx': 'useState, jsx-onClick, libreria cliente: sonner, importa cliente: components/data/RecordViews.tsx',
  'components/data/RecordViews.tsx': 'useState, jsx-onClick, useEffect',
  'components/export/ExportView.tsx': 'useState, useEffect, browser:document, jsx-onValueChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/label.tsx, importa cliente: components/ui/select.tsx',
  'components/export/ObsidianVaultCard.tsx': 'useState, browser:document, jsx-onClick, jsx-onOpenChange, importa cliente: components/ui/confirm-dialog.tsx',
  'components/forms/AccessRequestForm.tsx': 'useState, jsx-onSubmit',
  'components/forms/CountrySelectField.tsx': 'useState, jsx-onOpenChange, jsx-onChange, libreria cliente: react-hook-form, libreria cliente: react-select-country-list, importa cliente: components/ui/popover.tsx, importa cliente: components/ui/label.tsx, dynamic (menú cmdk diferido en CountrySelectCommand)',
  'components/forms/CountrySelectCommand.tsx': 'jsx-onSelect, importa cliente: components/ui/command.tsx (chunk diferido: solo se descarga al abrir el selector de país)',
  'components/forms/FileUploadInput.tsx': 'useRef, useState, useEffect, jsx-spread, jsx-onChange, libreria cliente: sonner',
  'components/forms/MutationForm.tsx': 'useRef, useState, jsx-spread, libreria cliente: sonner',
  'components/forms/SignUpForm.tsx': 'useRouter, jsx-onSubmit, libreria cliente: react-hook-form, libreria cliente: sonner, importa cliente: components/forms/CountrySelectField.tsx, importa cliente: components/forms/AccessRequestForm.tsx',
  'components/help/HelpTabs.tsx': 'importa cliente: components/ui/tabs.tsx',
  'components/historical-stress/HistoricalStressView.tsx': 'useState, jsx-onClick',
  'components/insider/InsiderSignalsView.tsx': 'useRouter, useState, jsx-onSubmit, jsx-onChange, jsx-onClick, importa cliente: components/data/RecordViews.tsx',
  'components/knowledge-graph/KnowledgeGraphCanvas.tsx': 'browser:document, useRouter, usePathname, useSearchParams, useState, useRef, browser:window, useEffect, browser:navigator, browser:ResizeObserver, browser:new ResizeObserver, jsx-onClick, jsx-onKeyDown, jsx-onPointerCancel, jsx-onPointerDown, jsx-onPointerLeave, jsx-onPointerMove, jsx-onPointerUp, jsx-onPointerEnter, jsx-onChange',
  'components/knowledge/DeleteCollectionButton.tsx': 'useState, jsx-onClick, jsx-onOpenChange, importa cliente: components/ui/confirm-dialog.tsx',
  'components/knowledge/DeleteDocumentButton.tsx': 'useState, jsx-onClick, jsx-onOpenChange, importa cliente: components/ui/confirm-dialog.tsx',
  'components/knowledge/ExtractionRefresh.tsx': 'useRouter, useEffect, browser:window, browser:document',
  'components/layout/BottomNav.tsx': 'usePathname, jsx-onClick, browser:window',
  'components/layout/ScrollPreserver.tsx': 'usePathname, useSearchParams, useEffect+useRef, browser:document/window',
  'components/layout/Breadcrumbs.tsx': 'usePathname',
  'components/layout/IntentLink.tsx': 'useState, jsx-onClick',
  'components/layout/SectionNav.tsx': 'usePathname',
  'components/layout/Sidebar.tsx': 'usePathname, useState, browser:document, jsx-onClick',
  // pestañas, sondeo cada minuto y botón de refresco manual del panel /mercados.
  'components/markets/LiveMarketsPanel.tsx': 'useState, useEffect, useCallback, jsx-onClick',
  'components/media/YouTubeEmbed.tsx': 'useState, jsx-onClick',
  'components/plan/DeleteContributionButton.tsx': 'useRouter, useState, jsx-onClick, importa cliente: components/ui/confirm-dialog.tsx',
  'components/plan/PlanContributionDialog.tsx': 'useRouter, useState, jsx-onOpenChange, jsx-onSubmit, jsx-onChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/dialog.tsx, importa cliente: components/ui/label.tsx',
  'components/plan/PlanSetupDialog.tsx': 'useRouter, useState, browser:document, jsx-onOpenChange, jsx-onSubmit, jsx-onChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/dialog.tsx, importa cliente: components/ui/label.tsx',
  'components/plan/PlanView.tsx': 'importa cliente: components/data/RecordViews.tsx, importa cliente: components/plan/PlanSetupDialog.tsx',
  'components/portfolio/AddTransactionButton.tsx': 'useState, jsx-onOpenChange, jsx-onPointerDown, jsx-onFocus, importa cliente: components/ui/dialog.tsx, dynamic (formulario de alta diferido en AddTransactionDialog)',
  'components/portfolio/AddTransactionDialog.tsx': 'useRouter, useState, jsx-onSubmit, jsx-onChange, jsx-onValueChange, libreria cliente: sonner, importa cliente: components/ui/select.tsx, importa cliente: components/search/TickerSearchInput.tsx (chunk diferido: solo se descarga al abrir el alta)',
  'components/portfolio/EditTransactionDialog.tsx': 'useRouter, useState, jsx-onOpenChange, jsx-onSubmit, jsx-onChange, jsx-onValueChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/dialog.tsx, importa cliente: components/ui/label.tsx, importa cliente: components/ui/select.tsx',
  'components/portfolio/SavingsProjection.tsx': 'useState, useEffect, jsx-onSubmit, jsx-onChange, jsx-onClick: edición de supuestos y preview asíncrono sin guardar',
  'components/portfolio/HoldingSignals.tsx': 'useState, useEffect',
  'components/portfolio/ImportIBKRButton.tsx': 'useState, useRef, useRouter, jsx-onChange, jsx-onClick, libreria cliente: sonner',
  'components/portfolio/PortfolioAllocation.tsx': 'dynamic-ssr-false, importa cliente: components/portfolio/PortfolioAllocationChart.tsx',
  'components/portfolio/PortfolioAllocationChart.tsx': 'libreria cliente: recharts',
  'components/portfolio/PortfolioHoldings.tsx': 'useRouter, useState, useEffect, jsx-onClick, libreria cliente: sonner',
  'components/portfolio/PortfolioNavChart.tsx': 'libreria cliente: recharts',
  'components/portfolio/PortfolioTabs.tsx': 'dynamic-ssr-false, useSearchParams, useRouter, usePathname, useState, useEffect, jsx-onValueChange, jsx-onClick, importa cliente: components/ui/tabs.tsx, importa cliente: components/portfolio/PortfolioSummary.tsx, importa cliente: components/portfolio/PortfolioHoldings.tsx, importa cliente: components/portfolio/PortfolioTransactions.tsx, importa cliente: components/portfolio/PortfolioAllocation.tsx, importa cliente: components/portfolio/PortfolioNavChart.tsx, importa cliente: components/portfolio/PortfolioScores.tsx, importa cliente: components/portfolio/PortfolioTearsheet.tsx, importa cliente: components/portfolio/AddTransactionButton.tsx, importa cliente: components/portfolio/RefreshPortfolioButton.tsx, importa cliente: components/portfolio/ImportIBKRButton.tsx',
  'components/portfolio/PortfolioTransactions.tsx': 'useRouter, useState, jsx-onClick, libreria cliente: sonner, importa cliente: components/portfolio/EditTransactionDialog.tsx, importa cliente: components/portfolio/ImportIBKRButton.tsx',
  'components/portfolio/RefreshPortfolioButton.tsx': 'useState, useRouter, jsx-onClick, libreria cliente: sonner',
  'components/portfolio/SyncDividendsButton.tsx': 'useState, useRouter, jsx-onClick, libreria cliente: sonner',
  'components/proPicks/EnhancedProPicksContent.tsx': 'useState, useRef, jsx-onFiltersChange, jsx-onApply, jsx-onClick, libreria cliente: sonner, importa cliente: components/proPicks/EnhancedProPicksFilters.tsx',
  'components/proPicks/EnhancedProPicksFilters.tsx': 'jsx-onClick, jsx-onValueChange, importa cliente: components/ui/label.tsx, importa cliente: components/ui/select.tsx',
  'components/proPicks/GemsView.tsx': 'useState, useEffect, jsx-onClick',
  'components/proPicks/MonthlyRebalanceView.tsx': 'useState, useRef, browser:document, jsx-onChange, jsx-onClick',
  'components/proPicks/ProPicksTabs.tsx': 'useState, useEffect, jsx-onValueChange, jsx-onStrategyChange, jsx-onClick, importa cliente: components/ui/tabs.tsx, importa cliente: components/proPicks/EnhancedProPicksContent.tsx, dynamic (vistas de pestañas no iniciales diferidas: se descargan al abrir cada pestaña)',
  'components/proPicks/StrategySelector.tsx': 'useRouter, jsx-onValueChange, importa cliente: components/ui/select.tsx',
  'components/proPicks/TrackRecordView.tsx': 'useState, useEffect, jsx-onClick',
  'components/pwa/InstallApp.tsx': 'browser:window, useState, useEffect, jsx-onClick',
  'components/research/AssistantRedirect.tsx': 'useEffect, useRouter, browser:window',
  'components/research/ChangesSinceVisit.tsx': 'useState, useEffect, browser:window',
  'components/research/BrainAskForm.tsx': 'useState, jsx-onSubmit, jsx-onChange, importa cliente: components/ui/button.tsx, importa cliente: components/ui/input.tsx',
  'components/research/ChatIntentLinks.tsx': 'jsx-onClick, importa cliente: components/ui/button.tsx',
  'components/research/LegacyChatRedirect.tsx': 'useRouter, usePathname, useEffect',
  'components/research/CompanyHeaderQuote.tsx': 'useState, useEffect, browser:document, browser:window, importa cliente: components/research/CompanyTechnicalWorkspace.tsx',
  'components/research/CompanyTechnicalChart.tsx': 'useState, useEffect, jsx-onClick, useRef, browser:window',
  'components/research/CompanyTechnicalWorkspace.tsx': 'dynamic-ssr-false, importa cliente: components/research/CompanyTechnicalChart.tsx',
  'components/research/ExternalNewsHeadline.tsx': 'useState, useRef, useEffect, browser:new IntersectionObserver, browser:IntersectionObserver',
  'components/research/GuideBrainButton.tsx': 'jsx-onClick, browser:window',
  'components/research/CompanyActionsMenu.tsx': 'popover de Radix (estado de apertura en cliente)',
  'components/ui/mobile-collapse.tsx': 'useState: bloque plegable en móvil',
  'components/research/GuideContextPanel.tsx': 'jsx-onClick, browser:window, importa cliente: components/ui/panel.tsx',
  'components/research/NewsHeadline.tsx': 'useState, useRef, useEffect, browser:new IntersectionObserver, browser:IntersectionObserver',
  'components/research/NewsSecondOrder.tsx': 'useState, jsx-onToggle',
  'components/research/NewsSummary.tsx': 'useState (traducción bajo demanda), fetch al pulsar Traducir',
  'components/research/NextStepLink.tsx': 'jsx-onClick, browser:window',
  'components/research/PrintButton.tsx': 'jsx-onClick, browser:window',
  'components/forms/FileUploadInputLazy.tsx': 'dynamic (frontera perezosa de FileUploadInput: canvas de imágenes fuera del bundle inicial de la ficha)',
  'components/research/QuickAlertButton.tsx': 'useState, jsx-onOpenChange, jsx-onPointerDown, jsx-onFocus, importa cliente: components/ui/popover.tsx, dynamic (cuerpo del popover diferido en QuickAlertPopoverBody)',
  'components/research/LazyMemoControls.tsx': 'dynamic (frontera perezosa de las islas del memorando: ThesisHumanInputForm, ThesisInvalidationRulesForm, ThesisDebatePanel)',
  'components/research/QuickAlertPopoverBody.tsx': 'useSyncExternalStore, useState, jsx-onValueChange, jsx-onChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/select.tsx (chunk diferido: solo se descarga al abrir el popover de alerta)',
  'components/research/ScrollToOnMount.tsx': 'useEffect, browser:document',
  'components/research/ShareCapitalPanel.tsx': 'jsx-onClick, useState, jsx-onChange, importa cliente: components/ui/panel.tsx, dynamic (gráfica recharts diferida en ShareCapitalChart)',
  'components/research/ShareCapitalChart.tsx': 'libreria cliente: recharts (chunk diferido: solo se descarga al cargar la gráfica de evolución)',
  'components/research/ThesisApproveButton.tsx': 'useRouter, useState, jsx-onClick, libreria cliente: sonner',
  'components/research/ThesisAudioPlayer.tsx': 'useState, useEffect, fetch al pulsar, jsx-onClick, jsx-onError',
  'components/research/ThesisDebatePanel.tsx': 'useState, jsx-onClick',
  'components/research/ThesisExportMenu.tsx': 'importa cliente: components/ui/dropdown-menu.tsx',
  'components/research/ThesisGenerateButton.tsx': 'useRouter, useState, useRef, useEffect, browser:document, browser:window, jsx-onClick',
  'components/research/ThesisMarkdownPager.tsx': 'useState, useRef, jsx-onClick, jsx-onChange',
  'components/research/ThesisHumanInputForm.tsx': 'useState, jsx-onSubmit',
  'components/research/ThesisInvalidationRulesForm.tsx': 'useState, jsx-onSubmit',
  'components/risk/RiskDashboardView.tsx': 'useState, useEffect, importa cliente: components/data/RecordViews.tsx',
  'components/screener/SectorSelect.tsx': 'useRouter y jsx-onChange: navegar al sector elegido sin perder scroll',
  'components/screener/FollowButton.tsx': 'useState, jsx-onClick, libreria cliente: sonner',
  'components/screeners/FilterFields.tsx': 'useState, jsx-onChange',
  'components/screeners/ScreenBreadcrumbName.tsx': 'useEffect, browser:window',
  'components/screeners/SubmitButton.tsx': 'useFormStatus',
  'components/security/TwoFactorSettings.tsx': 'useState, browser:navigator, jsx-onSubmit, jsx-onClick, libreria cliente: sonner, libreria cliente: react-hook-form, dynamic (QR qrcode.react diferido: solo se usa al activar 2FA)',
  'components/security/PrivacySettings.tsx': 'useState, useRouter, jsx-onSubmit, jsx-onClick, libreria cliente: sonner',
  'components/security/ChangePassword.tsx': 'useState, jsx-onSubmit, jsx-onClick, libreria cliente: sonner',
  'components/auth/ForgotPasswordForm.tsx': 'useState, jsx-onSubmit, jsx-onClick, libreria cliente: sonner',
  'components/auth/ResetPasswordForm.tsx': 'useState, useRouter, jsx-onSubmit, jsx-onClick, libreria cliente: sonner',
  'components/settings/TaxDeclarantForm.tsx': 'useState, jsx-onSubmit, jsx-onChange, libreria cliente: sonner',
  'components/settings/LlmSettingsForm.tsx': 'useMemo, useState, jsx-onSubmit, jsx-onChange, formulario controlado del proveedor LLM del tenant',
  'components/system/BackendOfflineAutoRetry.tsx': 'useRouter, useState, useEffect',
  // Estado de error en línea compartido: botón Reintentar con onClick.
  'components/system/SectionLoadError.tsx': 'jsx-onClick',
  'components/taxes/FilingSections.tsx': 'browser:document, jsx-onPreview, jsx-onReset, useState, jsx-onClick, importa cliente: components/data/RecordViews.tsx, importa cliente: components/taxes/TmePreviewForm.tsx',
  'components/taxes/TaxesView.tsx': 'browser:document, useRouter, useState, useEffect, jsx-onChange, jsx-onClick, jsx-onPreview, jsx-onReset, libreria cliente: sonner, importa cliente: components/data/RecordViews.tsx, importa cliente: components/taxes/FilingSections.tsx',
  'components/taxes/TmePreviewForm.tsx': 'useState, jsx-onSubmit, jsx-onChange, jsx-onClick',
  'components/ui/avatar.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-avatar',
  'components/ui/command.tsx': 'jsx-spread, jsx-onCloseAutoFocus, libreria cliente: cmdk, importa cliente: components/ui/dialog.tsx',
  'components/ui/confirm-dialog.tsx': 'jsx-onClick, jsx-onOpenChange, importa cliente: components/ui/dialog.tsx',
  'components/ui/dialog.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-dialog',
  'components/ui/dropdown-menu.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-dropdown-menu',
  'components/ui/label.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-label',
  'components/ui/overflow-scroll-region.tsx': 'useState, useRef, useEffect, useCallback, useId, browser:ResizeObserver, addEventListener scroll (pista visible de scroll horizontal solo con overflow real)',
  'components/ui/pagination.tsx': 'useState y jsx-onClick: página local de historial/afirmaciones sin convertir la ficha entera en cliente',
  'components/ui/panel.tsx': 'browser:HTMLElement, browser:window, jsx-spread, jsx-onClick',
  'components/ui/popover.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-popover',
  'components/ui/select.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-select',
  'components/ui/sonner.tsx': 'jsx-spread, libreria cliente: sonner',
  'components/ui/tabs.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-tabs',
  'components/ui/tooltip.tsx': 'jsx-spread, libreria cliente: @radix-ui/react-tooltip',
  'components/common/AnalystTargetLine.tsx': 'useState, useEffect: pide el consenso de objetivos tras el primer pintado (fuera del render de servidor)',
  'components/common/ExtendedHoursLine.tsx': 'useState, useEffect: pide la cotización extendida tras el primer pintado (fuera del render de servidor)',
  'components/watchlist/WatchlistAddButton.tsx': 'useState, jsx-onOpenChange, jsx-onPointerDown, jsx-onFocus, importa cliente: components/ui/dialog.tsx, dynamic (contenido del alta diferido en WatchlistAddDialog)',
  'components/watchlist/WatchlistBuyAction.tsx': 'useState, jsx-onOpenChange, jsx-onPointerDown, jsx-onFocus, importa cliente: components/ui/dialog.tsx, dynamic (formulario del alta diferido en AddTransactionDialog)',
  'components/watchlist/WatchlistAddDialog.tsx': 'useState, useRouter, jsx-onClick, libreria cliente: sonner, importa cliente: components/search/TickerSearchInput.tsx (chunk diferido: solo se descarga al abrir el alta)',
  'components/watchlist/WatchlistRemoveButton.tsx': 'useRouter, useState, jsx-onClick, libreria cliente: sonner',
  'components/work-products/WorkProductButton.tsx': 'useState, jsx-onOpenChange, jsx-onPointerDown, jsx-onFocus, importa cliente: components/ui/dialog.tsx, dynamic (diálogo de generación diferido en WorkProductDialog)',
  'components/work-products/WorkProductDialog.tsx': 'useState, jsx-onValueChange, jsx-onChange, jsx-onClick, libreria cliente: sonner, importa cliente: components/ui/label.tsx, importa cliente: components/ui/select.tsx, importa cliente: components/search/TickerSearchInput.tsx (chunk diferido: solo se descarga al abrir el diálogo)',
  'hooks/useOnlineStatus.ts': 'useSyncExternalStore, browser:window, browser:navigator',
  'lib/utils/scroll-anchor.ts': 'browser:window, browser:cancelAnimationFrame, browser:requestAnimationFrame, browser:document',
};

const audit = auditRepo(root, ['components', 'app', 'hooks', 'lib']);
const byRel = new Map(audit.map((r) => [r.rel, r]));

function unjustified(subdir: string, exceptions: Record<string, string>): string[] {
  return audit
    .filter((r) => r.hasUseClient && r.rel.startsWith(`${subdir}/`) && !r.justified)
    .map((r) => r.rel)
    .filter((rel) => !(rel in exceptions))
    .sort();
}

describe("'use client' justificado o inexistente", () => {
  it('ningún fichero de components/ lo usa sin motivo', () => {
    assert.deepEqual(unjustified('components', COMPONENTS_EXCEPTIONS), []);
  });

  it('ningún fichero de app/ lo usa sin motivo', () => {
    assert.deepEqual(unjustified('app', APP_EXCEPTIONS), []);
  });

  it('ningún fichero de hooks/ o lib/ lo usa sin motivo', () => {
    const offenders = audit
      .filter((r) => r.hasUseClient && (r.rel.startsWith('hooks/') || r.rel.startsWith('lib/')) && !r.justified)
      .map((r) => r.rel)
      .sort();
    assert.deepEqual(offenders, []);
  });
});

describe('el guard muerde de verdad (casos negativos)', () => {
  // Un guard que no puede fallar no es un guard. Se escriben ficheros REALES
  // en un temporal y se les pasa el MISMO codigo que recorre el repo, para
  // que lo que se demuestra es el caminho de ejecucion del guard, no una
  // funcion auxiliar del test.

  function auditTemp(files: Record<string, string>) {
    const dir = mkdtempSync(join(tmpdir(), 'd2c-use-client-'));
    try {
      for (const [rel, body] of Object.entries(files)) {
        const full = join(dir, rel);
        mkdirSync(dirname(full), { recursive: true });
        writeFileSync(full, body, 'utf8');
      }
      return auditRepo(dir, ['.']);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  }

  it('detecta un componente estatico con la directiva puesta', () => {
    // El caso real de D2c: HTML puro, ni un hook, ni un handler, y aun asi
    // el navegador recibe un modulo de JS para pintarlo.
    const rows = auditTemp({
      'components/Thing.tsx': `'use client';

export function Thing({ label }: { label: string }) {
  return <div className="p-2">{label}</div>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'components/Thing.tsx');
    assert.ok(row, 'el auditor no encontro el temporal');
    assert.equal(row.hasUseClient, true);
    assert.equal(row.justified, false, 'una directiva muerta debe marcarse como injustificada');
  });

  it('detecta la directiva muerta aunque el fichero use useMemo y useCallback', () => {
    // useMemo/useCallback se ejecutan en el render del servidor: no obligan a
    // la directiva. Sirven de caso negativo contra el atajo de "usa un hook,
    // luego es cliente".
    const rows = auditTemp({
      'components/MemoThing.tsx': `'use client';

import { useCallback, useMemo } from 'react';

const list = [1, 2, 3];

export function MemoThing() {
  const total = useMemo(() => list.reduce((a, b) => a + b, 0), []);
  const label = useCallback(() => String(total), [total]);
  return <p>{label()}</p>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'components/MemoThing.tsx');
    assert.equal(row?.justified, false, 'useMemo/useCallback no justifican la directiva');
  });

  it('detecta la directiva muerta en un archivo de app/ con la misma regla', () => {
    const rows = auditTemp({
      'app/(root)/algo/page.tsx': `'use client';

export default function Page() {
  return <main className="p-4">hola</main>;
}
`,
    });
    const row = rows.find((r) => r.rel === 'app/(root)/algo/page.tsx');
    assert.equal(row?.hasUseClient, true);
    assert.equal(row?.justified, false);
  });

  it('no se deja fooled por la palabra onClick en un string de copy', () => {
    // Un grep por "onClick" habria dado este fichero por bueno.
    const rows = auditTemp({
      'components/Copy.tsx': `'use client';

export function Copy() {
  return <p>Pulsa onClick para continuar</p>;
}
`,
    });
    assert.equal(rows.find((r) => r.rel === 'components/Copy.tsx')?.justified, false);
  });

  it('no se deja fooled por un useState declarado en el propio fichero', () => {
    // El detector mira el AST: un `function useState()` local no es el hook.
    const rows = auditTemp({
      'components/Fake.tsx': `'use client';

function useState<T>(initial: T): [T, () => void] {
  return [initial, () => {}];
}

export function Fake() {
  const [v] = useState('hola');
  return <span>{v}</span>;
}
`,
    });
    assert.equal(rows.find((r) => r.rel === 'components/Fake.tsx')?.justified, false);
  });
});

describe('el guard no muerde de mas (controles positivos)', () => {
  const CONTROL = `'use client';

%BODY%
`;

  /** Analiza un unico fichero con el MISMO camino que el guard del repo. */
  const justify = (body: string, rel = 'components/C.tsx') => {
    const rows = auditUseClient([analyzeSource(rel, CONTROL.replace('%BODY%', body))]);
    return rows[0];
  };

  const cases: Array<[string, string]> = [
    ['hook de estado', `import { useState } from 'react';\nexport function C() { const [a] = useState(1); return <p>{a}</p>; }`],
    ['efecto', `import { useEffect } from 'react';\nexport function C() { useEffect(() => {}, []); return <p />; }`],
    ['ref', `import { useRef } from 'react';\nexport function C() { const r = useRef(null); return <p />; }`],
    ['handler JSX', `export function C() { return <button onClick={() => {}}>x</button>; }`],
    ['usePathname', `import { usePathname } from 'next/navigation';\nexport function C() { return <p>{usePathname()}</p>; }`],
    ['useFormStatus', `import { useFormStatus } from 'react-dom';\nexport function C() { return <p>{useFormStatus().pending}</p>; }`],
    ['global de navegador', `export function C() { return <p>{typeof window}</p>; }`],
    ['dynamic ssr:false', `import dynamic from 'next/dynamic';\nconst D = dynamic(() => import('./D'), { ssr: false });\nexport function C() { return <D />; }`],
    ['libreria cliente', `import * as Tooltip from '@radix-ui/react-tooltip';\nexport function C() { return <div />; }`],
    ['spread de props', `export function C(p: object) { return <div {...p} />; }`],
  ];

  for (const [name, body] of cases) {
    it(`da por buena una directiva con ${name}`, () => {
      const row = justify(body);
      assert.equal(row.hasUseClient, true);
      assert.equal(row.justified, true, `una directiva con ${name} debe justificarse; reasons: ${row.reasons.join(', ')}`);
    });
  }

  it('da por buena una directiva que importa otro modulo cliente', () => {
    // Sin la directiva, este import seria un modulo de servidor importando
    // uno de cliente a traves de un tercero: Next lo resuelve, pero la
    // intencion del autor es clara y la directiva es lo que evita el error
    // de boundary en el ancestro comun.
    const analyzed = [
      analyzeSource('components/Leaf.tsx', `'use client';\nimport * as T from '@radix-ui/react-tooltip';\nexport function Leaf() { return <div />; }`),
      analyzeSource('components/Mid.tsx', `'use client';\nimport { Leaf } from './Leaf';\nexport function Mid() { return <Leaf />; }`),
    ];
    const rows = auditUseClient(analyzed);
    const mid = rows.find((r) => r.rel === 'components/Mid.tsx');
    assert.equal(mid?.justified, true, 'importar un modulo cliente justifica la directiva');
  });
});

describe('la lista de excepciones no crece sin motivo', () => {
  const MIN_REASON_LENGTH = 80;

  for (const [label, exceptions, subdir] of [
    ['components/', COMPONENTS_EXCEPTIONS, 'components'],
    ['app/', APP_EXCEPTIONS, 'app'],
  ] as Array<[string, Record<string, string>, string]>) {
    it(`cada excepcion de ${label} tiene un motivo escrito de verdad`, () => {
      for (const [rel, reason] of Object.entries(exceptions)) {
        assert.ok(rel.startsWith(`${subdir}`), `la excepcion ${rel} no pertenece a ${subdir}`);
        assert.equal(typeof reason, 'string', `${rel}: el motivo debe ser un string`);
        assert.ok(
          reason.trim().length >= MIN_REASON_LENGTH,
          `${rel}: motivo demasiado corto (${reason.trim().length} < ${MIN_REASON_LENGTH} caracteres). Una excepcion sin explicar es una barrera silenciosa.`,
        );
        assert.doesNotMatch(
          reason.trim(),
          /^(todo|tbd|porque si|fixme|pendiente|revisar|\?+)$/i,
          `${rel}: motivo de relleno, no vale.`,
        );
      }
    });

    it(`cada excepcion de ${label} sigue siendo necesaria`, () => {
      // Una excepcion que ya no aplica (el fichero quito la directiva, o
      //yncio un hook de verdad) es basura que hay que borrar, no deuda que
      // se arrastra: es la via por la que estas listas crecen solas.
      for (const [rel] of Object.entries(exceptions)) {
        assert.ok(existsSync(join(root, rel)), `${rel}: la excepcion apunta a un fichero que no existe. Bórrala.`);
        const row = byRel.get(rel);
        assert.ok(row, `${rel}: la excepcion apunta a un fichero que el auditor no encuentra. Bórrala.`);
        assert.equal(row.hasUseClient, true, `${rel}: ya no tiene 'use client', la excepcion es obsoleta. Bórrala.`);
        assert.equal(
          row.justified,
          false,
          `${rel}: ya tiene una señal de cliente que justifica la directiva. Bórrala de las excepciones.`,
        );
      }
    });
  }
});

describe('el escaner y el guard cuentan lo mismo', () => {
  it('LibraryChat justifica su directiva por el botón que abre el Cerebro', () => {
    const row = byRel.get('app/(root)/inversores/_components/LibraryChat.tsx');
    assert.ok(row);
    assert.equal(row.hasUseClient, true, 'el botón abre el Cerebro; solo GlobalBrain mantiene estado de conversacion');
    assert.equal(row.justified, true);
  });

  it('scan-use-client.mjs no reporta ninguna clase (B)', () => {
    // El escaner es la herramienta de lectura humana y el guard el que
    // bloquea. Si se desincronizasen, el guard pasaria en verde mientras el
    // inventario que se lee en la revision-prompts dice otra cosa.
    const rows = auditRepo(root, ['components', 'app', 'hooks', 'lib']);
    const dead = rows.filter((r) => r.hasUseClient && !r.justified && !(r.rel in COMPONENTS_EXCEPTIONS) && !(r.rel in APP_EXCEPTIONS));
    assert.deepEqual(
      dead.map((r) => r.rel).sort(),
      [],
      'el detector compartido encuentra directivas muertas que las excepciones no cubren',
    );
  });

  it('cada directiva client del repo esta en la allowlist, ni una mas ni una menos', () => {
    const actual = audit
      .filter((r) => r.hasUseClient && r.justified)
      .map((r) => r.rel)
      .sort();
    const faltan = actual.filter((rel) => !(rel in JUSTIFIED_USE_CLIENT));
    const sobran = Object.keys(JUSTIFIED_USE_CLIENT).filter((rel) => !actual.includes(rel));
    assert.deepEqual(
      faltan,
      [],
      "directivas 'use client' nuevas sin listar: anade cada ruta a JUSTIFIED_USE_CLIENT con su motivo",
    );
    assert.deepEqual(
      sobran,
      [],
      'entradas obsoletas en JUSTIFIED_USE_CLIENT (la directiva ya no existe o ya no se justifica): borralas',
    );
  });

  it('cada entrada de la allowlist existe, conserva la directiva y el detector la sigue justificando', () => {
    for (const [rel, reason] of Object.entries(JUSTIFIED_USE_CLIENT)) {
      assert.ok(typeof reason === 'string' && reason.trim().length > 0, `${rel}: motivo vacio`);
      assert.ok(existsSync(join(root, rel)), `${rel}: la entrada apunta a un fichero que no existe. Borrala.`);
      const row = byRel.get(rel);
      assert.ok(row, `${rel}: el auditor no encuentra el fichero. Borra la entrada.`);
      assert.equal(row.hasUseClient, true, `${rel}: ya no tiene 'use client'. Borra la entrada.`);
      assert.equal(
        row.justified,
        true,
        `${rel}: el detector ya no justifica la directiva: quita la directiva o borra la entrada.`,
      );
    }
  });

  it('las unicas directivas sin justificar son las excepciones listadas, ni una mas', () => {
    // Sin numero total: el conjunto de directivas muertas tiene que ser
    // exactamente el de las excepciones declaradas, ruta a ruta.
    const dead = audit
      .filter((r) => r.hasUseClient && !r.justified)
      .map((r) => r.rel)
      .sort();
    const exceptions = [...Object.keys(COMPONENTS_EXCEPTIONS), ...Object.keys(APP_EXCEPTIONS)].sort();
    assert.deepEqual(
      dead,
      exceptions,
      'una directiva muerta nueva necesita su excepcion con motivo (o quitar la directiva); una excepcion obsoleta se borra',
    );
  });
});
