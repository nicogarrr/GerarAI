/** ThesisApprovalService maps approve to ThesisVersion.status = published.
 *  "approved" is an approval-section state; "final" is not publication. */
export function thesisIsPublic(status: string | null | undefined): boolean {
    return status === 'published';
}
