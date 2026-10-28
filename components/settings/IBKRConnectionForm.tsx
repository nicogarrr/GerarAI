'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { connectIBKR, disconnectIBKR, syncIBKR, type IBKRConnection, type IBKRResult } from '@/lib/actions/ibkr-settings.actions';
import { formatDate } from '@/lib/format';

export default function IBKRConnectionForm({ initial }: { initial: IBKRConnection }) {
  const [connection, setConnection] = useState(initial);
  const [token, setToken] = useState('');
  const [query, setQuery] = useState(initial.query_id ?? '');
  const [account, setAccount] = useState(initial.account_id ?? '');
  const [complete, setComplete] = useState(initial.complete_query);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  function apply(result: IBKRResult) {
    if (result.ok) {
      setConnection(result.connection);
      setMessage(result.connection.message);
    } else setMessage(result.message);
  }

  async function connect(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage('Verificando el informe en IBKR. Puede tardar más de un minuto.');
    try {
      const result = await connectIBKR({ token, query_id: query, account_id: account, complete_query: complete });
      setToken('');
      apply(result);
      if (result.ok) {
        setMessage('Conexión verificada. Importando posiciones y caja…');
        apply(await syncIBKR());
      }
    } catch {
      setToken('');
      setMessage('No se pudo completar la conexión. Revisa los datos y vuelve a intentarlo.');
    } finally { setBusy(false); }
  }

  async function sync() {
    setBusy(true);
    setMessage('Solicitando un nuevo extracto a IBKR…');
    try { apply(await syncIBKR()); }
    catch { setMessage('No se pudo sincronizar. Conservamos los datos anteriores.'); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    setBusy(true);
    try { apply(await disconnectIBKR()); }
    catch { setMessage('No se pudo desconectar. La conexión puede seguir activa.'); }
    finally { setBusy(false); setConfirmDisconnect(false); }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-700/70 bg-gray-900/30 p-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium text-gray-100">{connection.connected ? `IBKR · ${connection.account_id}` : 'Vincula tu cuenta de IBKR'}</p>
          <span className="rounded-full border border-teal-700/60 px-2 py-1 text-xs text-teal-300">Solo lectura</span>
        </div>
        <p className="mt-2 text-gray-400">Una cuenta por cartera. Sin permisos para operar ni mover dinero.</p>
        {connection.last_success_at ? <p className="mt-2 text-gray-300">Última sincronización: {formatDate(connection.last_success_at)}. Extracto: {connection.statement_date ? formatDate(connection.statement_date) : 'sin fecha'}.</p> : null}
        <p className="mt-2 text-xs leading-relaxed text-gray-400">Actualización diaria · 06:50 UTC<br />Posiciones y caja del último extracto, no en tiempo real.</p>
      </div>
      <details className="rounded-lg border border-gray-800 px-4 py-2 text-sm">
        <summary className="min-h-11 cursor-pointer py-3 text-teal-300">Cómo conseguir token y Query ID</summary>
        <ol className="mt-2 list-decimal space-y-3 pl-5 text-gray-300">
          <li>En la web de IBKR, abre Informes → Flex Queries. Crea una Activity Flex Query de una sola cuenta.</li>
          <li>Incluye Open Positions, Cash Report y Trades; selecciona todas sus columnas. Usa XML, fechas yyyyMMdd y el último día de actividad.</li>
          <li>En Flex Web Service Configuration, activa el servicio y genera un token. Copia también el Query ID y tu cuenta IBKR.</li>
          <li>Pégalos aquí. Comprobaremos cuenta, fechas y columnas antes de importar.</li>
        </ol>
        <a className="mt-3 inline-flex min-h-11 items-center text-teal-300 underline" href="https://www.interactivebrokers.com/docs/web-api/flex-web-service/introduction" target="_blank" rel="noreferrer">Guía oficial de IBKR</a>
        <p className="mt-2 text-xs text-gray-400">El token caduca según el plazo elegido en IBKR. Se guarda cifrado y no se vuelve a mostrar. No necesitamos tu contraseña de IBKR.</p>
      </details>
      {!connection.connected ? (
        <form className="space-y-4 rounded-lg border border-gray-800 p-4" onSubmit={connect} aria-label="Conectar IBKR">
          <p className="text-sm font-medium text-gray-100">Datos de conexión</p>
          <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-token">
            <span>Token Flex</span>
            <Input className="h-11" autoComplete="new-password" id="ibkr-token" type="password" value={token} onChange={event => setToken(event.target.value)} disabled={busy} required />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-query">
              <span>Query ID</span>
              <Input className="h-11" autoComplete="off" id="ibkr-query" inputMode="numeric" value={query} onChange={event => setQuery(event.target.value)} disabled={busy} required />
            </label>
            <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-account">
              <span>Cuenta IBKR</span>
              <Input className="h-11" autoComplete="off" id="ibkr-account" placeholder="U1234567" value={account} onChange={event => setAccount(event.target.value)} disabled={busy || Boolean(connection.account_id)} required />
            </label>
          </div>
          <details className="text-sm text-gray-400">
            <summary className="min-h-11 cursor-pointer py-3 text-gray-300">Opciones de sincronización</summary>
          <label className="flex min-h-11 items-start gap-3 pb-3 text-sm text-gray-300">
            <input className="mt-0.5 size-5 shrink-0 accent-teal-500" type="checkbox" checked={complete} onChange={event => setComplete(event.target.checked)} disabled={busy} />
            <span>Confirmo que la consulta incluye toda esta cuenta, sin filtros. Permito cerrar posiciones y quitar saldos importados de IBKR que ya no aparezcan. Si no lo marco, solo se añaden o actualizan datos.</span>
          </label>
          </details>
          <Button className="h-11 w-full sm:w-auto" type="submit" disabled={busy || !token.trim() || !query.trim() || !account.trim()}>{busy ? 'Conectando…' : 'Conectar e importar'}</Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-3">
          <Button className="h-11" disabled={busy} onClick={() => void sync()}>{busy ? 'Sincronizando…' : 'Sincronizar ahora'}</Button>
          <Button className="h-11" variant="outline" disabled={busy} onClick={() => setConfirmDisconnect(true)}>Desconectar</Button>
        </div>
      )}
      {confirmDisconnect ? (
        <div role="alert" className="space-y-3 rounded-lg border border-amber-600/50 p-3 text-sm text-gray-300">
          <p>Se borrará el token guardado y se detendrán las próximas sincronizaciones. Conservaremos tus posiciones y operaciones. Para revocar el token en IBKR, hazlo también en su web.</p>
          <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void disconnect()}>Confirmar desconexión</Button><Button variant="outline" disabled={busy} onClick={() => setConfirmDisconnect(false)}>Cancelar</Button></div>
        </div>
      ) : null}
      <p role="status" aria-live="polite" className="text-sm leading-relaxed text-gray-300">{message || (connection.connected || connection.status !== 'not_connected' ? connection.message : '')}</p>
    </div>
  );
}
