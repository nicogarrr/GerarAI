'use client';

import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { connectIBKR, disconnectIBKR, syncIBKR, type IBKRConnection, type IBKRResult } from '@/lib/actions/ibkr-settings.actions';
import { useFormat, useT } from '@/lib/i18n/client';

export default function IBKRConnectionForm({ initial }: { initial: IBKRConnection }) {
  const t = useT();
  const { formatDate } = useFormat();
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
    setMessage(t('settings.ibkr.verifying'));
    try {
      const result = await connectIBKR({ token, query_id: query, account_id: account, complete_query: complete });
      setToken('');
      apply(result);
      if (result.ok) {
        setMessage(t('settings.ibkr.verifiedImporting'));
        apply(await syncIBKR());
      }
    } catch {
      setToken('');
      setMessage(t('settings.ibkr.connectFailed'));
    } finally { setBusy(false); }
  }

  async function sync() {
    setBusy(true);
    setMessage(t('settings.ibkr.requesting'));
    try { apply(await syncIBKR()); }
    catch { setMessage(t('settings.ibkr.syncFailed')); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    setBusy(true);
    try { apply(await disconnectIBKR()); }
    catch { setMessage(t('settings.ibkr.disconnectFailed')); }
    finally { setBusy(false); setConfirmDisconnect(false); }
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-gray-700/70 bg-gray-900/30 p-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-medium text-gray-100">{connection.connected ? `IBKR · ${connection.account_id}` : t('settings.ibkr.linkAccount')}</p>
          <span className="rounded-full border border-teal-700/60 px-2 py-1 text-xs text-teal-300">{t('settings.ibkr.readOnly')}</span>
        </div>
        <p className="mt-2 text-gray-400">{t('settings.ibkr.oneAccount')}</p>
        {connection.last_success_at ? <p className="mt-2 text-gray-300">{t('settings.ibkr.lastSync', { date: formatDate(connection.last_success_at), statement: connection.statement_date ? formatDate(connection.statement_date) : t('settings.ibkr.noDate') })}</p> : null}
        <p className="mt-2 text-xs leading-relaxed text-gray-400">{t('settings.ibkr.dailyUpdate')}<br />{t('settings.ibkr.notRealtime')}</p>
      </div>
      <details className="rounded-lg border border-gray-800 px-4 py-2 text-sm">
        <summary className="min-h-11 cursor-pointer py-3 text-teal-300">{t('settings.ibkr.howTitle')}</summary>
        <p className="mt-3 font-medium text-amber-200">{t('settings.ibkr.webOnly')}</p>
        <ol className="mt-3 list-decimal space-y-3 pl-5 text-gray-300">
          <li>{t('settings.ibkr.step1')}</li>
          <li>{t('settings.ibkr.step2')}</li>
          <li>{t('settings.ibkr.step3')}</li>
          <li>{t('settings.ibkr.step4')}</li>
          <li>{t('settings.ibkr.step5')}</li>
          <li>{t('settings.ibkr.step6')}</li>
          <li>{t('settings.ibkr.step7')}</li>
        </ol>
        <p className="mt-3 text-xs leading-relaxed text-gray-400">{t('settings.ibkr.flexNote')}</p>
        <div className="mt-3 flex flex-col gap-2">
          <a className="inline-flex min-h-11 items-center text-teal-300 underline" href="https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query.md" target="_blank" rel="noreferrer">{t('settings.ibkr.guideQuery')}</a>
          <a className="inline-flex min-h-11 items-center text-teal-300 underline" href="https://ibkrguides.com/clientportal/performanceandstatements/flex-web-service.htm" target="_blank" rel="noreferrer">{t('settings.ibkr.guideToken')}</a>
        </div>
        <p className="mt-2 text-xs text-gray-400">{t('settings.ibkr.tokenNote')}</p>
      </details>
      {!connection.connected ? (
        <form className="space-y-4 rounded-lg border border-gray-800 p-4" onSubmit={connect} aria-label={t('settings.ibkr.formAria')}>
          <p className="text-sm font-medium text-gray-100">{t('settings.ibkr.connectionData')}</p>
          <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-token">
            <span>{t('settings.ibkr.tokenLabel')}</span>
            <Input className="h-11" autoComplete="new-password" id="ibkr-token" type="password" value={token} onChange={event => setToken(event.target.value)} disabled={busy} required />
          </label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-query">
              <span>Query ID</span>
              <Input className="h-11" autoComplete="off" id="ibkr-query" inputMode="numeric" value={query} onChange={event => setQuery(event.target.value)} disabled={busy} required />
            </label>
            <label className="block space-y-1 text-sm text-gray-300" htmlFor="ibkr-account">
              <span>{t('settings.ibkr.accountLabel')}</span>
              <Input className="h-11" autoComplete="off" id="ibkr-account" placeholder="U1234567" value={account} onChange={event => setAccount(event.target.value)} disabled={busy || Boolean(connection.account_id)} required />
            </label>
          </div>
          <details className="text-sm text-gray-400">
            <summary className="min-h-11 cursor-pointer py-3 text-gray-300">{t('settings.ibkr.syncOptions')}</summary>
          <label className="flex min-h-11 items-start gap-3 pb-3 text-sm text-gray-300">
            <input className="mt-0.5 size-5 shrink-0 accent-teal-500" type="checkbox" checked={complete} onChange={event => setComplete(event.target.checked)} disabled={busy} />
            <span>{t('settings.ibkr.completeQuery')}</span>
          </label>
          </details>
          <Button className="h-11 w-full sm:w-auto" type="submit" disabled={busy || !token.trim() || !query.trim() || !account.trim()}>{busy ? t('settings.ibkr.connecting') : t('settings.ibkr.connectImport')}</Button>
        </form>
      ) : (
        <div className="flex flex-wrap gap-3">
          <Button className="h-11" disabled={busy} onClick={() => void sync()}>{busy ? t('settings.ibkr.syncing') : t('settings.ibkr.syncNow')}</Button>
          <Button className="h-11" variant="outline" disabled={busy} onClick={() => setConfirmDisconnect(true)}>{t('settings.ibkr.disconnect')}</Button>
        </div>
      )}
      {confirmDisconnect ? (
        <div role="alert" className="space-y-3 rounded-lg border border-amber-600/50 p-3 text-sm text-gray-300">
          <p>{t('settings.ibkr.disconnectWarning')}</p>
          <div className="flex flex-wrap gap-2"><Button disabled={busy} onClick={() => void disconnect()}>{t('settings.ibkr.confirmDisconnect')}</Button><Button variant="outline" disabled={busy} onClick={() => setConfirmDisconnect(false)}>{t('settings.ibkr.cancel')}</Button></div>
        </div>
      ) : null}
      <p role="status" aria-live="polite" className="text-sm leading-relaxed text-gray-300">{message || (connection.connected || connection.status !== 'not_connected' ? connection.message : '')}</p>
    </div>
  );
}
