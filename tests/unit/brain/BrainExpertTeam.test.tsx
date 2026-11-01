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
});
