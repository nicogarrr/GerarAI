"""Translate the actual SEC attempt receipt into thesis source provenance."""


def tracked_evidence(receipt: dict | None) -> dict:
    if not receipt:
        return {}
    status = receipt.get('status')
    reason = receipt.get('reason')
    fresh = status == 'ok' or (status == 'skipped' and reason == 'actualizado_ultimas_24h')
    detail = {
        'emisor_no_sec': 'Emisor fuera del ámbito SEC configurado.',
        'sec_no_disponible': 'SEC no disponible en el intento de actualización.',
        'sin_hechos_financieros': 'SEC consultada sin hechos financieros aprovechables.',
        'actualizado_ultimas_24h': 'Hechos SEC guardados y actualizados en las últimas 24 horas.',
    }.get(reason, 'Actualización SEC completada.' if fresh else 'Actualización SEC sin resultado confirmado.')
    return {'sources': {'fundamentals': {
        'status': 'ok' if fresh else 'pending',
        'source': 'SEC EDGAR companyfacts',
        'detail': detail,
        'facts_imported': receipt.get('facts_imported', 0),
        'last_refreshed_at': receipt.get('last_refreshed_at'),
    }}}
