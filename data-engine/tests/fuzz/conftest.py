"""El fuzzing es opt-in: RUN_FUZZ=1.

fuzz_app.py corta la red saliente, siembra la BD y parchea la auth a nivel de
módulo. Dentro de la suite normal (xdist) eso contaminaría a otros tests del
mismo worker, así que sin RUN_FUZZ=1 este directorio no se recoge.
"""

import os

if os.environ.get("RUN_FUZZ") != "1":
    collect_ignore_glob = ["test_*.py", "fuzz_app.py"]
