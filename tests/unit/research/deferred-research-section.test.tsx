import { expect, it, vi } from 'vitest';
import { Suspense } from 'react';
vi.mock('@/components/research/CompanyHeaderQuoteSkeleton', () => ({ CompanyHeaderQuoteSkeleton: () => <p>loading section</p> }));
import { DeferredResearchSection, ResearchSectionContent } from '@/components/research/DeferredResearchSection';
it('constructs a real Suspense boundary without invoking or awaiting the builder', async () => {
    const build = vi.fn(async () => <p>data</p>);
    const element = DeferredResearchSection({ build });
    expect(element.type).toBe(Suspense);
    expect(build).not.toHaveBeenCalled();
    expect(element.props.children.type).toBe(ResearchSectionContent);
    expect(await ResearchSectionContent({ build })).toEqual(<p>data</p>);
});
it('optional error retains inline warning; primary error reaches the route boundary', async () => {
    const error = new Error('offline');
    const build = vi.fn(async () => { throw error; });
    const onError = vi.fn(() => <p>retry</p>);
    expect(await ResearchSectionContent({ build, onError })).toEqual(<p>retry</p>);
    expect(onError).toHaveBeenCalledWith(error);
    await expect(ResearchSectionContent({ build })).rejects.toBe(error);
});
