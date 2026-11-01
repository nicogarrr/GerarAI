import { describe, expect, it } from 'vitest';
import { expertTeamFromResponse } from '@/lib/chat/expert-team';

describe('expertTeamFromResponse', () => {
    it('solo con model expert_team devuelve los expertos del plan, en orden y sin repetidos', () => {
        expect(expertTeamFromResponse({
            model: 'expert_team',
            llm_trace: { expert_team: { plan: ['fundamental', 'valuation', 'risk', 'risk'] } },
        })).toEqual(['fundamental', 'valuation', 'risk']);
    });
    it('cualquier otra respuesta no muestra nada', () => {
        expect(expertTeamFromResponse({ model: 'synthesis', llm_trace: { expert_team: { plan: ['risk'] } } })).toBeNull();
        expect(expertTeamFromResponse({ model: null })).toBeNull();
        expect(expertTeamFromResponse({})).toBeNull();
    });
    it('formas inesperadas o nombres desconocidos no se pintan', () => {
        expect(expertTeamFromResponse({ model: 'expert_team', llm_trace: null })).toBeNull();
        expect(expertTeamFromResponse({ model: 'expert_team', llm_trace: { expert_team: { plan: 'risk' } } })).toBeNull();
        expect(expertTeamFromResponse({ model: 'expert_team', llm_trace: { expert_team: { plan: ['<script>', 'tax'] } } })).toEqual(['tax']);
    });
});
