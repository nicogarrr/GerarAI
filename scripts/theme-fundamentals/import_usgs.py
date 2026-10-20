"""Reviewed CC0 USGS production and import-reliance snapshot, no price scraping."""
import csv
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
from urllib.request import urlopen

CATALOG = 'https://www.sciencebase.gov/catalog/item/'
PRODUCTION_ID = '69837e43b66b01367d7ec7c7'
RELIANCE_ID = '696a75d5d4be0228872d3bf8'
NAMES = {'Copper': 'Cobre', 'Lithium': 'Litio', 'Nickel': 'Níquel', 'Rare Earths': 'Tierras raras'}
COUNTRIES = {'Germany': 'Alemania', 'Japan': 'Japón', 'Kazakhstan': 'Kazajistán', 'Korea, Republic of': 'Corea del Sur', 'Poland': 'Polonia', 'Zambia': 'Zambia', 'Greenland': 'Groenlandia', 'Tanzania': 'Tanzania', 'United States': 'Estados Unidos', 'China': 'China', 'Australia': 'Australia', 'Chile': 'Chile', 'Peru': 'Perú', 'Indonesia': 'Indonesia', 'Brazil': 'Brasil', 'Argentina': 'Argentina', 'Canada': 'Canadá', 'Russia': 'Rusia', 'Zimbabwe': 'Zimbabue', 'Burma': 'Myanmar', 'Other countries': 'Otros países', 'World total (rounded)': 'Total mundial (redondeado)', 'World total': 'Total mundial', 'Congo (Kinshasa)': 'R. D. Congo', 'Philippines': 'Filipinas', 'New Caledonia': 'Nueva Caledonia', 'Madagascar': 'Madagascar', 'Nigeria': 'Nigeria', 'Vietnam': 'Vietnam', 'India': 'India', 'Malaysia': 'Malasia', 'Thailand': 'Tailandia', 'Mexico': 'México', 'Mali': 'Mali', 'Portugal': 'Portugal', 'Namibia': 'Namibia', 'South Africa': 'Sudáfrica', 'Bolivia': 'Bolivia'}


def number(v):
    if v.strip() in ('W', 'NA', '--', '-', '', chr(8212), chr(8211)):
        return None
    from math import isfinite
    n = float(v.replace(',', ''))
    if not isfinite(n) or n < 0:
        raise ValueError('Invalid USGS value')
    return n


def fetch_csv(item_id, name):
    with urlopen(CATALOG + item_id + '?format=json', timeout=30) as response:
        meta = json.load(response)
    file = next(f for f in meta['files'] if f['name'] == name)
    with urlopen(file['url'], timeout=30) as response:
        raw = response.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1252')
        return list(csv.DictReader(StringIO(text)))


def parse(production, reliance):
    series = []
    for commodity, spanish in NAMES.items():
        rows = [r for r in production if r['Commodity'] == commodity and r['Year'] == '2025'
                and r['Section'].startswith('World Mine') and r['Statistics_detail'] == 'Mine production']
        units = {r['Unit'] for r in rows}
        if not rows or len(units) != 1 or not units <= {'metric tons', 'thousand metric tons'}:
            raise ValueError('Unexpected production schema or unit')
        scale = 1000 if units == {'thousand metric tons'} else 1
        values = [{'label': COUNTRIES.get(r['Country'], r['Country']), 'values': [None if number(r['Value']) is None else number(r['Value']) * scale]} for r in rows]
        unit = 't de REO equivalente' if commodity == 'Rare Earths' else 't de contenido metálico'
        series.append(dict(title=spanish + ' · producción minera mundial', columns=['Producción estimada'], unit=unit,
                           rows=values, source=CATALOG + PRODUCTION_ID, sourceName='USGS MCS 2026 · CC0',
                           vintage='2025, estimación USGS', published='2026', kind='estimacion_oficial'))
    mapping = {'COPPER, refined': 'Cobre refinado', 'LITHIUM': 'Litio', 'NICKEL': 'Níquel', 'RARE EARTHS, compounds and metals': 'Tierras raras: compuestos y metales', 'GRAPHITE (NATURAL)': 'Grafito natural', 'COBALT': 'Cobalto'}
    selected = [r for r in reliance if r['Commodity'] in mapping]
    vals = []
    for r in selected:
        v = r['Net_Import_Reliance_pct_2025']
        # Preserve inequality exactly. Never pretend a lower bound is an observation.
        value = v if v.startswith(('>', '<')) else number(v)
        vals.append({'label': mapping[r['Commodity']], 'values': [value]})
    series.append(dict(title='EE. UU. · dependencia neta de importaciones', columns=['Consumo aparente cubierto con importaciones netas'], unit='%', rows=vals,
                       source=CATALOG + RELIANCE_ID, sourceName='USGS MCS 2026 · CC0', vintage='2025', published='2026', kind='estimacion_oficial'))
    return {'id': 'materiales', 'title': 'Materiales críticos', 'checkedAt': datetime.now(timezone.utc).date().isoformat(), 'metrics': [], 'series': series,
            'notes': ['Producción 2025 estimada por USGS, no cotización ni dato en vivo.', 'Tierras raras en equivalente de óxidos (REO); no se suman a toneladas de otros metales.', 'W y ausencias son N/D; los umbrales como >50 se conservan sin convertirlos en cifras exactas.', 'Los totales mundiales son filas de control de la fuente; no se suman otra vez con países.', 'Precios mensuales externos: sin serie incrustada hasta verificar derechos de los proveedores de cada referencia.'],
            'links': [{'label': 'Precios mensuales · World Bank Pink Sheet (fuente externa)', 'url': 'https://www.worldbank.org/en/research/commodity-markets'}, {'label': 'Datos y licencia CC0 · USGS', 'url': 'https://www.usgs.gov/data/mineral-commodity-summaries-2026-data-release'}]}


if __name__ == '__main__':
    data = parse(fetch_csv(PRODUCTION_ID, 'MCS2026_Commodities_Data.csv'), fetch_csv(RELIANCE_ID, 'MCS2026_Fig2_Net_Import_Reliance.csv'))
    Path('data/theme-fundamentals/materiales.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
