'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AlertCircle } from 'lucide-react';
import { useT } from '@/lib/i18n/client';

interface Props {
    children: ReactNode;
    fallback?: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
    errorInfo: ErrorInfo | null;
}

/**
 * Error Boundary para capturar errores de React
 * Muestra un mensaje amigable en lugar de romper toda la aplicación
 */
export class ErrorBoundary extends Component<Props, State> {
    constructor(props: Props) {
        super(props);
        this.state = {
            hasError: false,
            error: null,
            errorInfo: null,
        };
    }

    static getDerivedStateFromError(error: Error): Partial<State> {
        return {
            hasError: true,
            error,
        };
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        // Log error para debugging
        console.error('ErrorBoundary caught an error:', error, errorInfo);
        
        this.setState({
            error,
            errorInfo,
        });

        // Aquí podrías enviar el error a un servicio de logging
        // Por ejemplo: Sentry, LogRocket, etc.
    }

    handleReset = () => {
        this.setState({
            hasError: false,
            error: null,
            errorInfo: null,
        });
    };

    render() {
        if (this.state.hasError) {
            // Si hay un fallback custom, usarlo
            if (this.props.fallback) {
                return this.props.fallback;
            }

            // UI por defecto para errores (componente función: el boundary
            // es una clase y no puede llamar hooks; el copy va con useT()).
            return (
                <ErrorFallback
                    error={this.state.error}
                    errorInfo={this.state.errorInfo}
                    onReset={this.handleReset}
                />
            );
        }

        return this.props.children;
    }
}

function ErrorFallback({ error, errorInfo, onReset }: { error: Error | null; errorInfo: ErrorInfo | null; onReset: () => void }) {
    const t = useT();
    return (
        <div className="flex items-center justify-center min-h-[400px] p-4">
            <Card className="w-full max-w-md">
                <CardHeader>
                    <div className="flex items-center gap-2">
                        <AlertCircle className="h-5 w-5 text-destructive" />
                        <CardTitle>{t('shell.error.title')}</CardTitle>
                    </div>
                    <CardDescription>
                        {t('shell.error.body')}
                    </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                    {process.env.NODE_ENV === 'development' && error && (
                        <details className="text-sm">
                            <summary className="cursor-pointer text-muted-foreground mb-2">
                                {t('shell.error.devDetails')}
                            </summary>
                            <pre className="bg-muted p-2 rounded overflow-auto text-xs">
                                {error.toString()}
                                {errorInfo?.componentStack}
                            </pre>
                        </details>
                    )}
                    <div className="flex gap-2">
                        <Button onClick={onReset} variant="outline">
                            {t('shell.error.retry')}
                        </Button>
                        <Button
                            onClick={() => window.location.reload()}
                            variant="default"
                        >
                            {t('shell.error.reload')}
                        </Button>
                    </div>
                </CardContent>
            </Card>
        </div>
    );
}

/**
 * HOC para envolver componentes con Error Boundary
 */
export function withErrorBoundary<P extends object>(
    Component: React.ComponentType<P>,
    fallback?: ReactNode
) {
    const WrappedComponent = (props: P) => (
        <ErrorBoundary fallback={fallback}>
            <Component {...props} />
        </ErrorBoundary>
    );

    WrappedComponent.displayName = `withErrorBoundary(${Component.displayName || Component.name || 'Component'})`;

    return WrappedComponent;
}

