import { Readable } from 'node:stream';
import { createRequire } from 'node:module';
import { act, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
const m = vi.hoisted(() => ({ targets: vi.fn(), history: vi.fn() }));
vi.mock('@/lib/actions/analyst-panels.actions', () => ({ readAnalystTargets: m.targets, readAnalystHistory: m.history }));
vi.mock('@/lib/i18n/client', () => ({ useT: () => (key: string) => key }));
vi.mock('@/components/research/AnalystTargetsView', () => ({ AnalystTargetsView: ({ data }: any) => <p>{data?.symbol ?? 'targets unavailable'}</p> }));
import { DeferredAnalystTargets } from '@/components/research/DeferredAnalystPanels';
const require = createRequire(import.meta.url);
const { createFromNodeStream } = require('next/dist/compiled/react-server-dom-turbopack/client.node');

// Decode an actual Flight promise using the project's installed Next/React
// runtime. Its inherited catch() returns undefined, not a chained Promise.
async function flightInitial(symbol: string, rejected = false) {
    const row = rejected ? '1:E{"digest":"fixture-rejection","message":"fixture unavailable","name":"Error","stack":[],"env":"Server"}\n' : `1:${JSON.stringify({ symbol })}\n`;
    const root = createFromNodeStream(Readable.from(['0:{"initial":"$@1"}\n', row]),
        { moduleMap: {}, serverModuleMap: {}, moduleLoading: null });
    return await new Promise<{ initial: Promise<any> }>((resolve, reject) => root.then(resolve, reject));
}
beforeEach(() => { vi.clearAllMocks(); });
it.each(['GOOGL', 'MSFT'])('renders actual decoded RSC initial targets for %s', async symbol => {
    const { initial } = await flightInitial(symbol);
    expect(initial.catch(() => null)).toBeUndefined();
    render(<DeferredAnalystTargets symbol={symbol} initial={initial} />);
    await screen.findByText(symbol);
    expect(m.targets).not.toHaveBeenCalled();
});
it('a rejected decoded RSC promise shows honest unavailable instead of crashing', async () => {
    const { initial } = await flightInitial('MSFT', true);
    render(<DeferredAnalystTargets symbol="MSFT" initial={initial} />);
    await screen.findByText('targets unavailable');
});
it('unmount before an RSC thenable resolves does not update the stale panel', async () => {
    let resolve!: (data: any) => void;
    const initial = { then: (done: (value: any) => void) => { resolve = done; } } as unknown as Promise<any>;
    const view = render(<DeferredAnalystTargets symbol="MSFT" initial={initial} />);
    await act(async () => {});
    view.unmount();
    await act(async () => resolve({ symbol: 'stale MSFT' }));
    expect(screen.queryByText('stale MSFT')).toBeNull();
});
