/** Only a complete, disabled chat availability response is not a model call.
 * Unknown or malformed server actions stay suspicious (fail closed).
 */
export function isDisabledChatAvailabilityResponse(body: string): boolean {
    // Next's Flight stream puts each JSON result on its own numbered row.
    const results: unknown[] = [];
    for (const line of body.split('\n')) {
        const match = /^[0-9a-f]+:(.*)$/i.exec(line);
        if (!match) continue;
        if (line.startsWith('0:') || /^D"\$[0-9a-f]+"$/i.test(match[1])) continue; // Transport metadata.
        let result: unknown;
        try { result = JSON.parse(match[1]); } catch { return false; }
        results.push(result);
    }
    if (results.length !== 1) return false;
    const result = results[0];
    if (result && typeof result === 'object' && !Array.isArray(result)) {
        const data = result as Record<string, unknown>;
        const keys = Object.keys(data).sort();
        if (keys.join(',') !== 'can_start,feature,reason,retry_after_seconds,state') return false;
        if (data.feature === 'chat' && data.state === 'off' && data.can_start === false
            && data.reason === 'disabled' && data.retry_after_seconds === null) return true;
    }
    return false;
}
