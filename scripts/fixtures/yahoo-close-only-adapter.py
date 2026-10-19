"""Execute the repository's real Yahoo candle adapter without importing the API app.

AST extraction isolates this one adapter from heavyweight optional API dependencies.
The function body is never rewritten. Fake HTTP only supplies the upstream payload.
"""
import ast
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
httpx = SimpleNamespace(Client=object, HTTPError=Exception)

module = ast.parse(Path('data-engine/app/api/routes/market.py').read_text())
functions = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == '_fetch_yahoo_candles']
# yahoo_chart_symbol vive en el conector compartido (market.py lo importa con
# alias _yahoo_chart_symbol); se extrae de su modulo real igual que el adapter.
connector = ast.parse(Path('data-engine/app/services/connectors/yahoo.py').read_text())
functions += [node for node in connector.body if isinstance(node, ast.FunctionDef) and node.name == 'yahoo_chart_symbol']
namespace = {'math': math, 'httpx': httpx, '_YAHOO_CHART_URL': 'https://query1.finance.yahoo.com/v8/finance/chart', '_SHARE_CLASS_DOTTED': re.compile(r'^([A-Z]{1,5})\.([AB])$')}
exec(compile(ast.Module(body=functions, type_ignores=[]), '<real-market-adapter>', 'exec'), namespace)
namespace['_yahoo_chart_symbol'] = namespace['yahoo_chart_symbol']
class Response:
    status_code = 200
    def json(self):
        return json.loads(sys.stdin.read())
class Client:
    def get(self, *args, **kwargs):
        return Response()
print(json.dumps(namespace['_fetch_yahoo_candles'](Client(), 'HIMS', 0, 2000000000, '1d')))
