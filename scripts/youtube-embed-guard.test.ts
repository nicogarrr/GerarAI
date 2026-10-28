import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: extensión necesaria para node --experimental-strip-types.
import { isYouTubeVideoId, isYouTubeChannelUrl, isVideoTimestamp, validInvestorVideos } from '../lib/ui/youtube-video.ts';

const video = {
    video_id: 'aB_12-cDE34', title: 'Una entrevista', published_at: '2026-10-06T15:00:00Z',
    channel_kind: 'personal_confirmed', channel_name: 'Canal', channel_url: 'https://www.youtube.com/@canal',
};

describe('vídeos de inversores', () => {
    it('limita el ID y los destinos a YouTube', () => {
        assert.equal(isYouTubeVideoId(video.video_id), true);
        for (const id of ['', '../watch?v=x', 'bad?id=1234', null]) assert.equal(isYouTubeVideoId(id), false);
        assert.equal(isYouTubeChannelUrl(video.channel_url), true);
        assert.equal(isYouTubeChannelUrl('https://www.youtube.com/channel/UCIALMKvObZNtJ6AmdCLP7Lg'), true);
        for (const url of ['https://youtube.com.evil.test/@canal', 'javascript:alert(1)', 'http://www.youtube.com/@canal', 'https://user@youtube.com/@canal', 'https://youtube.com/watch?v=aB_12-cDE34']) {
            assert.equal(isYouTubeChannelUrl(url), false);
        }
    });
    it('sin datos y payloads inválidos no inventan vídeos', () => {
        for (const data of [undefined, null, {}, [], [null], [{ ...video, published_at: 'bad' }], [{ ...video, title: ' ' }], [{ ...video, channel_kind: undefined }], [{ ...video, channel_kind: 'unknown' }], [{ ...video, channel_url: 'https://evil.test' }]]) {
            assert.deepEqual(validInvestorVideos(data), []);
        }
    });
    it('exige fecha calendárica real y zona explícita', () => {
        for (const stamp of ['2026-02-30T15:00:00Z', '2026-04-31T12:00:00Z', '2026-10-06T15:00:00', '2026-02-29T12:00:00Z', '2026-10-06T24:00:00Z', '2026-10-06T15:00:00+02:60']) {
            assert.equal(isVideoTimestamp(stamp), false, stamp);
            assert.deepEqual(validInvestorVideos([{ ...video, published_at: stamp }]), []);
        }
        for (const stamp of ['2024-02-29T12:00:00Z', '2026-10-06T15:00:00+02:00', '2026-10-06T15:00:00.123Z']) assert.equal(isVideoTimestamp(stamp), true, stamp);
    });
    it('deduplica, ordena recientes y limita a seis', () => {
        assert.equal(validInvestorVideos([video, video]).length, 1);
        const old = { ...video, video_id: 'bB_12-cDE34', published_at: '2026-10-05T12:00:00Z' };
        assert.deepEqual(validInvestorVideos([old, video]).map((v) => v.video_id), [video.video_id, old.video_id]);
        const many = Array.from({ length: 8 }, (_, i) => ({ ...video, video_id: `${i}B_12-cDE34` }));
        assert.equal(validInvestorVideos(many).length, 6);
    });
    it('CSP permite los reproductores de YouTube explícitamente', () => {
        // La CSP vive en lib/security/csp.ts (nonce por middleware), no en
        // next.config.ts.
        const cspModule = readFileSync('lib/security/csp.ts', 'utf8');
        assert.match(cspModule, /frame-src https:\/\/www\.youtube-nocookie\.com https:\/\/www\.youtube\.com/);
        assert.match(cspModule, /frame-ancestors 'self'/);
    });
    it('iframe solo tras clic, nocookie, con título y alternativa externa', () => {
        const embed = readFileSync('components/media/YouTubeEmbed.tsx', 'utf8');
        assert.match(embed, /useState\(false\)/);
        assert.match(embed, /onClick=\{\(\) => setLoaded\(true\)\}/);
        assert.match(embed, /https:\/\/www\.youtube-nocookie\.com\/embed\//);
        assert.match(embed, /title=\{title\}/);
        assert.match(embed, /isYouTubeVideoId\(videoId\)/);
        const block = readFileSync('app/(root)/inversores/_components/InvestorVideos.tsx', 'utf8');
        assert.match(block, /No hay vídeos verificados disponibles/);
        assert.match(block, /Fuente:/);
        assert.match(block, /video\.channel_kind === 'archive'/);
        assert.match(block, /Archivo, fuente no confirmada/);
        assert.match(block, /<time dateTime=/);
        assert.match(block, /Ver en YouTube/);
        assert.match(readFileSync('app/(root)/inversores/[slug]/page.tsx', 'utf8'), /<InvestorVideos videos=\{investor\.videos\}/);
    });
});


describe('published_at backend/frontend contract', () => {
    it('accepts the exact backend serializations without dropping valid fractions', () => {
        const cases = JSON.parse(readFileSync('scripts/investor-video-timestamp-contract.json', 'utf8')) as { input: string; output: string }[];
        for (const row of cases) {
            assert.equal(isVideoTimestamp(row.input), true, row.input);
            assert.equal(isVideoTimestamp(row.output), true, row.output);
            assert.equal(validInvestorVideos([{ ...video, published_at: row.output }]).length, 1);
            assert.equal(Date.parse(row.input), Date.parse(row.output));
        }
        assert.equal(isVideoTimestamp('2026-10-01T10:00:00.1234567Z'), false);
    });
});
