'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { RefreshCw } from 'lucide-react';
import { updateAllPortfolioPrices } from '@/lib/actions/portfolio.actions';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { useT } from '@/lib/i18n/client';

interface RefreshPortfolioButtonProps {
    userId: string;
}

export default function RefreshPortfolioButton({ userId }: RefreshPortfolioButtonProps) {
    const ti = useT();
    const [isRefreshing, setIsRefreshing] = useState(false);
    const router = useRouter();

    async function handleFullRefresh() {
        try {
            setIsRefreshing(true);

            // Invalida las lecturas cacheadas (15 s) y las relee del backend.
            // NO dispara POST /api/portfolio/refresh-market: ese endpoint
            // refresca el universo completo de empresas del tenant y tarda
            // minutos, así que aquí solo se releen los datos que el servidor
            // tiene guardados.
            await updateAllPortfolioPrices(userId);

            // Vuelve a renderizar los KPIs del servidor con lo releído.
            router.refresh();
            // El toast dice lo que pasó: lecturas rehechas contra el servidor.
            // «Cartera actualizada» afirmaba precios nuevos que este botón no
            // puede pedir.
            toast.success(ti('portfolio.refresh.toast'));

        } catch (error) {
            showErrorToast(error, { onRetry: handleFullRefresh });
        } finally {
            // Small delay to allow the page to refresh
            setTimeout(() => setIsRefreshing(false), 1000);
        }
    }

    return (
        <Button
            variant="outline"
            size="icon"
            onClick={handleFullRefresh}
            disabled={isRefreshing}
            aria-busy={isRefreshing}
            aria-label={isRefreshing ? ti('portfolio.refresh.ariaUpdating') : ti('portfolio.refresh.ariaUpdate')}
            title={ti('portfolio.refresh.title')}
            className="h-11 w-11 shrink-0 border-gray-600 text-gray-200 hover:bg-gray-700 sm:h-9 sm:w-9"
        >
            <RefreshCw aria-hidden="true" className={isRefreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />
        </Button>
    );
}
