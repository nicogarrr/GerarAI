/**
 * Request deduplication and in-memory caching layer
 * Prevents duplicate API calls and improves app fluidity
 */

interface CacheEntry<T> {
    data: T;
    timestamp: number;
    promise?: Promise<T>;
}

export class RequestCache {
    private cache = new Map<string, CacheEntry<unknown>>();
    private pendingRequests = new Map<string, Promise<unknown>>();

    /**
     * Get cached data or execute the fetcher function
     * Deduplicates concurrent requests to the same key
     */
    async get<T>(
        key: string,
        fetcher: () => Promise<T>,
        ttlSeconds: number = 60
    ): Promise<T> {
        const now = Date.now();
        const cached = this.cache.get(key);

        // Return cached data if still valid
        if (cached && (now - cached.timestamp) < ttlSeconds * 1000) {
            return cached.data as T;
        }

        // If there's a pending request, wait for it instead of making a new one
        const pending = this.pendingRequests.get(key);
        if (pending) {
            return pending as Promise<T>;
        }

        // Create new request
        const promise = fetcher()
            .then((data) => {
                // Solo repuebla la caché si esta promesa sigue siendo la
                // vigente para la clave: un invalidate() durante el vuelo
                // borra la entrada de pendingRequests, y sin este guard el
                // .then tardío reintroduciría el dato obsoleto DESPUÉS de
                // la invalidación (race invalidación-repoblación).
                if (this.pendingRequests.get(key) === promise) {
                    this.cache.set(key, { data, timestamp: now });
                    this.pendingRequests.delete(key);
                }
                return data;
            })
            .catch((error) => {
                if (this.pendingRequests.get(key) === promise) {
                    this.pendingRequests.delete(key);
                }
                throw error;
            });

        this.pendingRequests.set(key, promise);
        return promise;
    }

    /**
     * Invalidate cached entry
     */
    invalidate(key: string): void {
        this.cache.delete(key);
        this.pendingRequests.delete(key);
    }

    /**
     * Clear all cache
     */
    clear(): void {
        this.cache.clear();
        this.pendingRequests.clear();
    }

    /**
     * Clear expired entries
     */
    clearExpired(ttlSeconds: number = 300): void {
        const now = Date.now();
        for (const [key, entry] of this.cache.entries()) {
            if ((now - entry.timestamp) >= ttlSeconds * 1000) {
                this.cache.delete(key);
            }
        }
    }
}

// Singleton instance
export const requestCache = new RequestCache();

// Auto-cleanup every 5 minutes
if (typeof window !== 'undefined') {
    setInterval(() => {
        requestCache.clearExpired();
    }, 5 * 60 * 1000);
}
