/** Mount point for the single layout-owned Cerebro, not another assistant. */
export function LibraryChat({ scope = 'letters', authors = [], documentId, documentTitle, placement = 'center' }: { documentId?: number; documentTitle?: string; placement?: 'center' | 'reader'; scope?: 'letters' | 'library'; authors?: string[] }) {
  return <div id="brain-library-slot" data-placement={placement} data-document-id={documentId} data-document-title={documentTitle} data-scope={scope} data-authors={JSON.stringify(authors)} />;
}
