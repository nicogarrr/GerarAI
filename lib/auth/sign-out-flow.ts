export type SignOutResult = { success: boolean; error?: string };

export interface SignOutDeps {
    signOut: () => Promise<SignOutResult>;
    push: (path: string) => void;
    refresh: () => void;
    notifyError: (title: string, description: string) => void;
}

/** Cierra sesión: solo navega a /sign-in si el servidor confirmó el cierre. */
export async function runSignOut(deps: SignOutDeps): Promise<boolean> {
    let result: SignOutResult;
    try {
        result = await deps.signOut();
    } catch {
        result = { success: false };
    }
    if (!result.success) {
        deps.notifyError('No se pudo cerrar la sesión', result.error ?? 'Recarga la página e inténtalo de nuevo.');
        return false;
    }
    deps.push('/sign-in');
    deps.refresh();
    return true;
}
