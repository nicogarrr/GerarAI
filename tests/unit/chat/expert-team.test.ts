import { describe, expect, it } from 'vitest';
import { expertTeamFromResponse, expertTeamSummaryFromResponse, expertTeamTimeoutsFromResponse } from '@/lib/chat/expert-team';

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

describe('quién respondió y quién no llegó a tiempo', () => {
    const response = {
        model: 'expert_team',
        llm_trace: { expert_team: { plan: ['fundamental', 'valuation', 'risk'], answered: ['fundamental', 'risk'], timed_out: ['valuation'] } },
    };
    it('con la traza nueva, «respondieron» son solo los que contestaron', () => {
        expect(expertTeamFromResponse(response)).toEqual(['fundamental', 'risk']);
    });
    it('los que no respondieron a tiempo, aparte', () => {
        expect(expertTeamTimeoutsFromResponse(response)).toEqual(['valuation']);
        expect(expertTeamTimeoutsFromResponse({ ...response, llm_trace: { expert_team: { plan: ['risk'], timed_out: [] } } })).toBeNull();
        expect(expertTeamTimeoutsFromResponse({ model: 'synthesis', llm_trace: response.llm_trace })).toBeNull();
        expect(expertTeamTimeoutsFromResponse({ model: 'expert_team', llm_trace: { expert_team: { timed_out: ['<b>', 'news'] } } })).toEqual(['news']);
    });
});

describe('resumen compacto por experto', () => {
    const rows = [
        { expert: 'fundamental', status: 'ok', stance: 'positive', cited: 3, dropped: 0, confidence: 'high' },
        { expert: 'risk', status: 'ok', stance: 'negative', cited: 1, dropped: 2, confidence: 'low' },
        { expert: 'valuation', status: 'timeout', stance: 'neutral', cited: 0, dropped: 0, confidence: null },
    ];
    it('solo los que contestaron con fuente, en orden', () => {
        expect(expertTeamSummaryFromResponse({ model: 'expert_team', llm_trace: { expert_team: { experts: rows } } })).toEqual([
            { expert: 'fundamental', stance: 'positive', cited: 3, total: 3, confidence: 'high' },
            { expert: 'risk', stance: 'negative', cited: 1, total: 3, confidence: 'low' },
        ]);
    });
    it('otra respuesta, traza antigua o formas raras: nada o se descartan', () => {
        expect(expertTeamSummaryFromResponse({ model: 'synthesis', llm_trace: { expert_team: { experts: rows } } })).toBeNull();
        expect(expertTeamSummaryFromResponse({ model: 'expert_team', llm_trace: { expert_team: { plan: ['risk'] } } })).toBeNull();
        expect(expertTeamSummaryFromResponse({
            model: 'expert_team',
            llm_trace: { expert_team: { experts: [
                { expert: '<b>', stance: 'positive', cited: 2, dropped: 0, confidence: 'high' },
                { expert: 'news', stance: 'eufórico', cited: 2, dropped: 0, confidence: 'certísima' },
                { expert: 'tax', stance: 'neutral', cited: -1, dropped: 0, confidence: 'low' },
                'risk',
            ] } },
        })).toEqual([{ expert: 'news', stance: 'neutral', cited: 2, total: 2, confidence: null }]);
    });
});
