import { withAuthErrors } from '@/lib/auth/route-auth';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { proxyZipDownload } from '@/lib/research/zip-proxy';

/** Proxy privado: la firma Research OS nunca llega al navegador. */
async function getHandler() {
  await requireAuthenticatedUser();
  return proxyZipDownload({
    path: '/api/obsidian/vault.zip',
    filename: 'gerarai-obsidian-vault.zip',
    exportErrorDetail: 'No se pudo exportar el vault de Obsidian',
  });
}

export const GET = withAuthErrors(getHandler);
