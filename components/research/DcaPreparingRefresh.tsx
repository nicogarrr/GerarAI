/** Compatibility marker for preparing DCA/news widgets.
 * Automatic full-page refresh is disabled: every refresh re-ran all research
 * workspaces, and remounting reset the old 20-attempt budget. Preparing text
 * stays visible in the parent; the user can refresh manually when wanted.
 * A future partial-card reader must have its own persistent retry budget.
 */
export default function DcaPreparingRefresh() {
    return null;
}
