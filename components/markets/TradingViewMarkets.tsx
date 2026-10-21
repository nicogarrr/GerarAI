import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

/**
 * Panel /mercados con el widget OFICIAL Market Overview de TradingView
 * (https://www.tradingview.com/widget-docs/getting-started/): producto
 * pensado y licenciado por ellos para embeberse en sitios de terceros,
 * gratis y sin key, con su atribución visible. No hay fetch propio a
 * ningún proveedor: los datos los sirve TradingView dentro de su iframe.
 *
 * Cobertura VERIFICADA símbolo a símbolo en el widget real (21-oct-2026):
 * - Índices EU de contado: BME:IBC y STOXX:SX5E con marca D (delayed),
 *   EURONEXT:PX1 (CAC 40) con D, XETR:DAX con E (EOD). La marca la pone
 *   el propio widget en cada fila; no la inferimos.
 * - Acciones ES: las 12 probadas una a una (BME:*), todas con D.
 * - Divisas: FX:* en tiempo real según la FAQ oficial de datos.
 * - CFD: índices USA/Nikkei/FTSE y parte de las materias primas SOLO
 *   existen como CFD (FOREXCOM/OANDA/PEPPERSTONE/FX). No son el índice
 *   ni el futuro oficial: pestaña y nombre lo dicen.
 * - Sin cobertura encontrada en esta prueba: futuros CME/COMEX/NYMEX
 *   (ES1!, GC1!, CL1!...), VIX, Russell 2000. Quedan FUERA hasta tener
 *   fuente; la prueba es de este widget, no de todo TradingView.
 */

type SymbolSpec = { s: string; d: string };

type Group = {
    key: string;
    label: string;
    /** Nota honesta sobre qué es cada fila de esta pestaña. */
    note: string;
    symbols: SymbolSpec[];
};

const GROUPS: Group[] = [
    {
        key: 'indices',
        label: 'Índices',
        note: 'Índices de contado. La marca de cada fila la pone TradingView: D = datos con retraso, E = cierre del día (EOD).',
        symbols: [
            { s: 'BME:IBC', d: 'IBEX 35' },
            { s: 'STOXX:SX5E', d: 'Euro Stoxx 50' },
            { s: 'EURONEXT:PX1', d: 'CAC 40' },
            { s: 'XETR:DAX', d: 'DAX' },
        ],
    },
    {
        key: 'indices-cfd',
        label: 'Índices (CFD)',
        note: 'CFD sobre índices: réplicas de brokers, NO el índice oficial ni futuros. El índice de contado USA no está disponible en esta fuente; se muestra lo que hay, etiquetado.',
        symbols: [
            { s: 'FOREXCOM:SPXUSD', d: 'S&P 500 (CFD)' },
            { s: 'FOREXCOM:NSXUSD', d: 'Nasdaq 100 (CFD)' },
            { s: 'FOREXCOM:DJI', d: 'Dow Jones (CFD)' },
            { s: 'FOREXCOM:UK100', d: 'FTSE 100 (CFD)' },
            { s: 'OANDA:JP225USD', d: 'Nikkei 225 (CFD)' },
        ],
    },
    {
        key: 'acciones',
        label: 'Acciones ES',
        note: 'Valores del IBEX 35 con datos de BME con retraso (marca D). Selección fija, no un ranking por volumen.',
        symbols: [
            { s: 'BME:BBVA', d: 'BBVA' },
            { s: 'BME:SAN', d: 'Banco Santander' },
            { s: 'BME:IBE', d: 'Iberdrola' },
            { s: 'BME:ITX', d: 'Inditex' },
            { s: 'BME:REP', d: 'Repsol' },
            { s: 'BME:IDR', d: 'Indra' },
            { s: 'BME:TEF', d: 'Telefónica' },
            { s: 'BME:CABK', d: 'CaixaBank' },
            { s: 'BME:AMS', d: 'Amadeus' },
            { s: 'BME:AENA', d: 'Aena' },
            { s: 'BME:ELE', d: 'Endesa' },
            { s: 'BME:FER', d: 'Ferrovial' },
        ],
    },
    {
        key: 'materias',
        label: 'Materias primas',
        note: 'Oro y plata al contado (spot); crudo, cobre y gas como CFD. No son futuros: los futuros no están disponibles en esta fuente.',
        symbols: [
            { s: 'OANDA:XAUUSD', d: 'Oro (spot)' },
            { s: 'OANDA:XAGUSD', d: 'Plata (spot)' },
            { s: 'FX:USOIL', d: 'Petróleo WTI (CFD)' },
            { s: 'FX:UKOIL', d: 'Petróleo Brent (CFD)' },
            { s: 'PEPPERSTONE:COPPER', d: 'Cobre (CFD)' },
            { s: 'OANDA:NATGASUSD', d: 'Gas natural (CFD)' },
        ],
    },
    {
        key: 'divisas',
        label: 'Divisas',
        note: 'Cruces en tiempo real según la documentación de datos de TradingView (forex real-time).',
        symbols: [
            { s: 'FX:EURUSD', d: 'EUR/USD' },
            { s: 'FX:EURGBP', d: 'EUR/GBP' },
            { s: 'FX:GBPUSD', d: 'GBP/USD' },
            { s: 'FX:USDJPY', d: 'USD/JPY' },
            { s: 'FX_IDC:EURJPY', d: 'EUR/JPY' },
        ],
    },
];

/** Cabecera de pestaña + filas + atribución: medida sobre el widget real. */
// Medida real del widget (QA 21-oct): ~64 px por fila, no 108.
const widgetHeight = (rows: number) => 46 + rows * 64 + 30;

function TradingViewMarketRows({ group }: { group: Group }) {
    /*
     * iframe DIRECTO al documento oficial del widget en el origen de
     * TradingView (https://www.tradingview-widget.com/embed-widget/market-overview/?locale=es#<config>),
     * estructura y claves observadas en el DOM real por QA (21-oct-2026,
     * config decodificada completa). Aislamiento REAL por origen cruzado
     * (SOP): el script de TradingView corre en SU origen, sin acceso al
     * DOM, cookies ni almacenamiento de la app; por eso ya no hace falta
     * s3.tradingview.com en script-src. El sandbox refuerza: allow-scripts
     * + allow-same-origin (del ORIGEN DEL WIDGET, no de la app) +
     * popups para su atribución/enlaces. QA verificó render 4/4 filas y 0
     * errores; sandbox sin allow-same-origin deja el widget en blanco.
     */
    const config = {
        colorTheme: 'dark',
        dateRange: '1D',
        showChart: false,
        width: '100%',
        height: '100%',
        isTransparent: true,
        showSymbolLogo: true,
        showFloatingTooltip: false,
        tabs: [{ title: group.label, symbols: group.symbols }],
        utm_source: '',
        utm_medium: 'widget',
        utm_campaign: 'market-overview',
        'page-uri': '__NHTTP__',
    };
    const src = `https://www.tradingview-widget.com/embed-widget/market-overview/?locale=es#${encodeURIComponent(JSON.stringify(config))}`;
    return (
        <iframe
            title={group.label}
            src={src}
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
            style={{ width: '100%', height: widgetHeight(group.symbols.length), border: 0 }}
        />
    );
}

export function TradingViewMarkets() {
    return (
        <div className="mt-4">
            <Tabs defaultValue="indices">
                <TabsList className="h-auto flex-wrap">
                    {GROUPS.map((group) => (
                        <TabsTrigger key={group.key} value={group.key}>
                            {group.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
                {GROUPS.map((group) => (
                    <TabsContent key={group.key} value={group.key} forceMount className="data-[state=inactive]:hidden">
                        <p className="my-2 text-xs leading-5 text-gray-500">{group.note}</p>
                        <TradingViewMarketRows group={group} />
                    </TabsContent>
                ))}
            </Tabs>
            <div className="mt-4 text-xs leading-5 text-gray-500">
                Fuente: widget oficial de TradingView, servido por ellos dentro de esta página. La marca de
                cada fila (D = retraso, E = cierre del día) la aplica el proveedor; las divisas van en tiempo
                real según su documentación. No son datos oficiales de mercado ni sirven para operar con
                garantías.{' '}
                <details className="mt-1">
                    <summary className="cursor-pointer text-gray-400">Cobertura pendiente</summary>
                    <span className="mt-1 block">
                        Sin cobertura encontrada en esta fuente: futuros reales (CME/COMEX/NYMEX), VIX y
                        Russell 2000 (tampoco como CFD verificado). Si aparecen en el widget con permiso, se
                        añadirán; hasta entonces no se muestran para no falsear la cobertura.
                    </span>
                </details>
            </div>
        </div>
    );
}
