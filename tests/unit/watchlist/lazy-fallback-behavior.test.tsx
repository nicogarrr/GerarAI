import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
vi.mock('next/dynamic',()=>({default:(_load:unknown,options:{loading:()=>React.ReactNode})=>options.loading}));
import { LazyDcaEvaluateButton, LazyDcaHitRatesPopover, LazyDcaWatchCardToggle } from '@/components/watchlist/LazyDcaControls';
describe('deferred DCA controls announce pending chunks',()=>{it('provides a localized loading status for every unavailable control, without enabling actions',()=>{render(<LocaleProvider locale="en"><LazyDcaEvaluateButton/><LazyDcaHitRatesPopover symbol="MSFT"/><LazyDcaWatchCardToggle symbol="MSFT"/></LocaleProvider>);expect(screen.getAllByRole('status')).toHaveLength(3);for(const status of screen.getAllByRole('status'))expect(status).toHaveAccessibleName(/load/i);expect(screen.queryByRole('button')).not.toBeInTheDocument();});});
