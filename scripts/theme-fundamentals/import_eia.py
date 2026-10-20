"""Refresh reviewed EIA snapshots. Run manually, review diff before publishing.
No API key needed. Withheld/missing values stay null; editions must agree.
"""
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.request import urlopen

from openpyxl import load_workbook

BASE = 'https://www.eia.gov/uranium/marketing/xls/'
URLS = {
    'coverage': BASE + 'umartable12figure11.xlsx',
    'unfilled': BASE + 'umartable11figure10.xlsx',
    'price': BASE + 'umartable7.xlsx',
    'production': 'https://www.eia.gov/uranium/production/quarterly/xls/qupd_tbl1.xlsx',
}


def number(value, divisor=1):
    if value is None or str(value).strip() in {'W', '-', '--', '.', 'NA', 'N/D'}:
        return None
    from math import isfinite
    n = float(value)
    if not isfinite(n) or n < 0:
        raise ValueError('Invalid source value')
    return n / divisor


def parse(tables):
    edition = re.match(r'(\d{4}) Uranium Marketing', str(tables['coverage'][0][0]))
    if not edition:
        raise ValueError('Unknown EIA edition')
    year = edition.group(1)
    for key in ('coverage', 'unfilled', 'price'):
        if not str(tables[key][0][0]).startswith(year + ' Uranium Marketing'):
            raise ValueError('Mixed EIA editions')
        if 'thousand pounds' not in str(tables[key][5][0]):
            raise ValueError('Unexpected source units')
    if 'dollars per pound' not in tables['price'][5][0]:
        raise ValueError('Unexpected price unit')
    if tables['production'][5][0] != 'pounds U3O8':
        raise ValueError('Unexpected production unit')
    coverage = []
    for row in tables['coverage'][8:]:
        if isinstance(row[0], int):
            coverage.append({'label': str(row[0]), 'values': [number(v, 1000) for v in row[1:4]]})
        elif row[0] == 'Total':
            totals = [number(v, 1000) for v in row[1:4]]
    unfilled = [{'label': str(r[0]), 'values': [number(r[3], 1000)]}
                for r in tables['unfilled'][9:] if isinstance(r[0], int) and r[0] > int(year)]
    price = next(r for r in tables['price'][9:] if r[0] == 'Total')
    production = next(r for r in tables['production'] if r[0] == 'Total production')
    periods = tables['production'][7]
    def series(title, columns, unit, rows, url, vintage, published):
        return dict(title=title, columns=columns, unit=unit, rows=rows, source=url,
                    sourceName='EIA', vintage=vintage, published=published, kind='reportado')
    pub = str(tables['coverage'][1][0]).replace('Release Date: ', '').replace('July', 'julio')
    return {'id': 'nuclear', 'title': 'Uranio', 'checkedAt': datetime.now(timezone.utc).date().isoformat(),
            'series': [
                series('Necesidades sin contratar · EE. UU.', ['Sin contratar'], 'millones lb U3O8e', unfilled, URLS['unfilled'], '31/12/' + year, pub),
                series('Cobertura contractual máxima · EE. UU.', ['Contratado máximo', 'Sin contratar', 'Total máximo'], 'millones lb U3O8e', coverage, URLS['coverage'], '31/12/' + year, pub),
                series('Precio medio pagado · entregas ' + year, ['Contratos spot', 'Largo plazo', 'Total'], 'USD/lb U3O8e', [{'label': year, 'values': [number(price[2]), number(price[4]), number(price[6])]}], URLS['price'], 'Entregas ' + year, pub),
                series('Producción de concentrado · EE. UU.', ['Producción'], 'millones lb U3O8', [{'label': str(periods[i]).replace('Q', 'T'), 'values': [number(production[i], 1e6)]} for i in range(2, 7)], URLS['production'], str(tables['production'][0][0]).replace('Domestic Uranium Production Report 2nd Quarter', 'Producción US, T2'), str(tables['production'][1][0]).replace('Release Date: ', '').replace('August', 'agosto')),
            ],
            'metrics': [{'label': 'Necesidades sin contratar · acumulado', 'value': totals[1], 'unit': 'millones lb U3O8e', 'period': f'{int(year)+1}–{int(year)+10}', 'source': URLS['coverage'], 'vintage': '31/12/' + year}],
            'notes': ['Solo utilities de EE. UU.; sin contratar no significa escasez física.', 'Precios de entregas históricas, no cotización spot actual.', 'W y ausencias se muestran como N/D; no se reconstruyen por diferencias.'],
            'links': [{'label': 'Precio indicativo externo · Cameco (UxC/TradeTech)', 'url': 'https://www.cameco.com/invest/markets/uranium-price'}]}


if __name__ == '__main__':
    tables = {}
    for key, url in URLS.items():
        with urlopen(url, timeout=30) as response:
            tables[key] = list(load_workbook(BytesIO(response.read()), data_only=True).active.values)
    payload = parse(tables)
    target = Path('data/theme-fundamentals/nuclear.json')
    if target.exists():
        prior = json.loads(target.read_text())
        payload['series'] += [s for s in prior['series'] if s['sourceName'].startswith('NEA/IAEA')]
        payload['notes'] += [n for n in prior['notes'] if n.startswith(('Contexto mundial', 'Fuente: OECD'))]
    Path('data/theme-fundamentals/nuclear.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
