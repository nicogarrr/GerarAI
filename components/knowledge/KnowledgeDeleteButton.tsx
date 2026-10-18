'use client';

import { useState } from 'react';
import { Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { deleteKnowledgeDocument } from '@/lib/actions/research-tools.actions';
import { getFriendlyErrorMessage } from '@/lib/types/errors';

/** Borrado de un documento de conocimiento con confirmación propia en dos
 *  pasos (nada de confirm() nativo): el primer clic despliega el aviso de lo
 *  que se pierde y el segundo ejecuta. */
export function KnowledgeDeleteButton({ documentId, title }: { documentId: number; title: string }) {
  const [confirming, setConfirming] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onConfirm() {
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      await deleteKnowledgeDocument(documentId);
      toast.success('Documento borrado');
    } catch (err) {
      setError(getFriendlyErrorMessage(err));
      setPending(false);
      setConfirming(false);
    }
  }

  if (!confirming) {
    return (
      <Button size="sm" variant="outline" onClick={() => setConfirming(true)}>
        <Trash2 aria-hidden="true" className="h-4 w-4" />Borrar
      </Button>
    );
  }
  return (
    <div className="flex max-w-xs flex-col items-end gap-2 text-right">
      <p className="text-xs leading-5 text-gray-400">
        ¿Borrar «{title}»? Se eliminan el documento, sus fragmentos y los principios extraídos, también los ya aprobados. Los casos de estudio se conservan sin el enlace y el archivo original sigue en el almacén. No se puede deshacer.
      </p>
      <div className="flex gap-2">
        <Button size="sm" variant="ghost" disabled={pending} onClick={() => setConfirming(false)}>Cancelar</Button>
        <Button size="sm" variant="destructive" disabled={pending} onClick={onConfirm}>
          {pending ? 'Borrando…' : 'Sí, borrar'}
        </Button>
      </div>
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </div>
  );
}
