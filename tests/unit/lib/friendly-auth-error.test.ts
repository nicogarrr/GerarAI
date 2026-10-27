import { describe, expect, it } from 'vitest';

import { AuthenticationError, AuthorizationError, getFriendlyErrorMessage } from '@/lib/types/errors';

describe('getFriendlyErrorMessage ante sesión caducada o sin permiso', () => {
    it('la sesión caducada de requireAuthenticatedUser no llega en inglés', () => {
        expect(getFriendlyErrorMessage(new AuthenticationError('User not authenticated'))).toBe(
            'Necesitas iniciar sesión para continuar.',
        );
    });

    it('un 403 local dice que no hay permiso', () => {
        expect(getFriendlyErrorMessage(new AuthorizationError('Forbidden: tenant mismatch'))).toBe(
            'No tienes permiso para esta operación.',
        );
    });
});
