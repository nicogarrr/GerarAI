import { Suspense, type ReactNode } from 'react';
import { CompanyHeaderQuoteSkeleton } from './CompanyHeaderQuoteSkeleton';

export async function ResearchSectionContent({ build, onError }: { build: () => Promise<ReactNode>; onError?: (error: unknown) => ReactNode }) {
    try { return await build(); }
    catch (error) {
        if (onError) return onError(error);
        throw error;
    }
}

/** Do not await a section while constructing the company shell. */
export function DeferredResearchSection(props: Parameters<typeof ResearchSectionContent>[0]) {
    return <Suspense fallback={<CompanyHeaderQuoteSkeleton />}><ResearchSectionContent {...props} /></Suspense>;
}
