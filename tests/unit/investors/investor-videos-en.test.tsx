import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/components/media/YouTubeEmbed', () => ({ YouTubeEmbed: ({ title }: { title: string }) => <div>{title}</div> }));

import { InvestorVideos } from '@/app/(root)/inversores/_components/InvestorVideos';
import { LocaleProvider } from '@/lib/i18n/client';

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('Vídeos de inversores en inglés', () => {
    it('sin vídeos, el estado vacío sale en inglés', () => {
        en(<InvestorVideos videos={[]} />);
        expect(screen.getByRole('heading', { name: 'Videos' })).toBeTruthy();
        expect(screen.getByText('There are zero verified videos for this investor.')).toBeTruthy();
        expect(screen.getByRole('link', { name: 'See investing channels' })).toBeTruthy();
    });

    it('en español el estado vacío no cambia', () => {
        render(<InvestorVideos videos={[]} />);
        expect(screen.getByText('No hay vídeos verificados disponibles para este inversor.')).toBeTruthy();
    });
});
