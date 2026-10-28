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
        <p className="mt-3 font-medium text-amber-200">Debe hacerse desde la web de IBKR (Portal del Cliente), no desde la app móvil.</p>
        <ol className="mt-3 list-decimal space-y-3 pl-5 text-gray-300">
          <li>Entra en el Portal del Cliente de IBKR desde el navegador. La guía oficial indica Performance &amp; Reports → Flex Queries; también ofrece Menú → Reporting → Flex Queries. No hemos comprobado los nombres exactos de esos menús en español ni en tu cuenta.</li>
          <li>Crea una Activity Flex Query para una sola cuenta, sin filtros que excluyan posiciones o movimientos. Usa XML. Para la sincronización diaria, elige el último día de actividad disponible: el cierre del extracto debe tener como máximo 5 días de antigüedad, y posiciones y caja deben corresponder al mismo cierre. Esto no limita a 5 días todo el historial de operaciones.</li>
          <li>Activa Open Positions, Cash Report, Trades y Cash Transactions. Para completar el historial y contrastar los cálculos, añade Currency Conversion Rate, Transfers y Corporate Actions. Selecciona todos los campos disponibles en esas secciones, incluidos Account ID, Currency, Report Date, identificadores de operación, cantidades, precios, costes y comisiones. No todas las cuentas ofrecen los mismos campos.</li>
          <li>Opcionalmente, añade Statement of Funds, Forex Balances, Change in Dividend Accruals y Open Dividend Accruals. Son datos de contraste: incluirlos no significa que todos alimenten ya los cálculos de GerarAI. En Open Positions, conserva el nivel Summary para el total de cada posición; los lotes son un detalle adicional, no un sustituto de ese total. No hemos comprobado las opciones exactas de formato y niveles que ofrece tu pantalla.</li>
          <li>Guarda la consulta. En Flex Queries, abre el icono de información junto a ella y copia el Query ID que aparece arriba. Es el identificador de la consulta, no el número de cuenta.</li>
          <li>En Flex Queries → Flex Web Service Configuration, abre el engranaje de configuración y activa el servicio. Copia el token y comprueba su caducidad. Generar uno nuevo invalida el anterior. Si restringes el token por IP, debe permitir la IP del servidor de GerarAI, no solo la de tu móvil u ordenador.</li>
          <li>Vuelve a este formulario e introduce token, Query ID y la cuenta IBKR exacta del extracto. No compartas el token por chat. Al pulsar Conectar e importar verificaremos el informe y, si es válido, importaremos los datos. IBKR puede tardar en prepararlo. Deja sin marcar la opción de consulta completa hasta confirmar que incluye toda la cuenta: esa opción permite cerrar posiciones y retirar saldos ausentes.</li>
        </ol>
        <p className="mt-3 text-xs leading-relaxed text-gray-400">Flex ofrece extractos, no datos en tiempo real. Una operación reciente puede no aparecer hasta que IBKR prepare el siguiente informe. Para un historial fiscal completo puede hacer falta una importación histórica adicional; el último cierre por sí solo no garantiza que estén todas las operaciones.</p>
        <div className="mt-3 flex flex-col gap-2">
          <a className="inline-flex min-h-11 items-center text-teal-300 underline" href="https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query.md" target="_blank" rel="noreferrer">Guía oficial: consulta y Query ID</a>
          <a className="inline-flex min-h-11 items-center text-teal-300 underline" href="https://ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm" target="_blank" rel="noreferrer">Guía oficial: activar el servicio y obtener el token</a>
        </div>
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
