import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BrainExpertTeam } from '@/components/brain/BrainExpertTeam';
import { LocaleProvider } from '@/lib/i18n/client';

describe('Cerebro: aviso del equipo de expertos', () => {
    it('dice quién respondió y, aparte, quién no llegó a tiempo', () => {
        render(<BrainExpertTeam experts={['fundamental', 'risk']} timedOut={['valuation']} />);
        const box = screen.getByTestId('brain-expert-team');
        expect(box).toHaveTextContent('Respuesta del equipo de expertos: Fundamental · Riesgo');
        expect(screen.getByTestId('brain-expert-team-timeout')).toHaveTextContent(
            'No respondió a tiempo: Valoración. La respuesta usa lo que sí contestaron los demás.',
        );
    });

    it('sin expertos lentos no hay aviso de tiempo', () => {
        render(<BrainExpertTeam experts={['fundamental', 'risk']} timedOut={null} />);
        expect(screen.queryByTestId('brain-expert-team-timeout')).toBeNull();
    });

    it('en inglés', () => {
        render(
            <LocaleProvider locale="en">
                <BrainExpertTeam experts={['news']} timedOut={['tax', 'valuation']} />
            </LocaleProvider>,
        );
        expect(screen.getByTestId('brain-expert-team-timeout')).toHaveTextContent(
            'Did not answer in time: Tax · Valuation. The answer uses what the others did answer.',
        );
    });

    it('resumen compacto por experto con su postura y confianza', () => {
        render(
            <BrainExpertTeam
                experts={['fundamental', 'risk']}
                timedOut={null}
                summary={[
                    { expert: 'fundamental', stance: 'positive', cited: 3, total: 3, confidence: 'high' },
                    { expert: 'risk', stance: 'negative', cited: 1, total: 3, confidence: 'low' },
                ]}
            />,
        );
        const rows = screen.getByTestId('brain-expert-team-summary').querySelectorAll('li');
        expect(rows).toHaveLength(2);
        expect(rows[0]).toHaveTextContent('Fundamental: a favor · confianza alta · 3 de 3 afirmaciones con fuente');
        expect(rows[1]).toHaveTextContent('Riesgo: en contra · confianza baja · 1 de 3 afirmaciones con fuente');
    });

    it('resumen en inglés, y sin resumen no se pinta la lista', () => {
        const { unmount } = render(
            <LocaleProvider locale="en">
                <BrainExpertTeam experts={['news']} summary={[{ expert: 'news', stance: 'neutral', cited: 2, total: 2, confidence: null }]} />
            </LocaleProvider>,
        );
        expect(screen.getByTestId('brain-expert-team-summary')).toHaveTextContent('News: neutral · 2 of 2 claims sourced');
        unmount();
        render(<BrainExpertTeam experts={['news']} />);
        expect(screen.queryByTestId('brain-expert-team-summary')).toBeNull();
    });
});
