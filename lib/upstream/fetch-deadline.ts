/** Keep the deadline alive through headers AND body consumption. */
export async function withFetchDeadline<T>(
    run: (signal: AbortSignal) => Promise<T>,
    timeoutMs: number,
): Promise<T> {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const expired = new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
            controller.abort();
            reject(new DOMException('Request deadline exceeded', 'TimeoutError'));
        }, timeoutMs);
    });
    try {
        return await Promise.race([run(controller.signal), expired]);
    } finally {
        clearTimeout(timer);
    }
}
