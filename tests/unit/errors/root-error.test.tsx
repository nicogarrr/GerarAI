import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import RootError from '@/app/(root)/error';

describe('RootError never exposes private error messages', () => {
  for (const message of [
    'PRIVATE_SENTINEL database password rejected',
    'fetch failed PRIVATE_SENTINEL',
    'Minified React error #418 PRIVATE_SENTINEL',
  ]) {
    it(message.split('PRIVATE_SENTINEL')[0] || 'unexpected error', () => {
      const html = renderToStaticMarkup(<RootError error={new Error(message)} reset={() => {}} />);
      expect(html).not.toContain('PRIVATE_SENTINEL');
      expect(html).toContain('role="alert"');
      expect(html).toContain(message.startsWith('fetch failed')
        ? 'El motor de datos no está disponible'
        : 'Se produjo un error inesperado');
    });
  }
});
