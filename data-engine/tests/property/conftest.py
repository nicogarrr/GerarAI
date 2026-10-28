"""Suite de propiedades (Hypothesis) del dinero, la fiscalidad y las senales.

Cada test enuncia un invariante («sin coste conocido no hay ganancia», «una
subunidad se divide entre 100 una sola vez», «el nivel DCA es monotono en el
descuento»...) y Hypothesis busca un contraejemplo. Los bugs que encontro al
escribirla estan arreglados con su test de regresion propio (#2590, #2591,
#2592, #2602).

Perfiles:

- ``ci`` (por defecto): 60 ejemplos por test, sin deadline y derandomizado,
  para que un rojo en CI sea reproducible en local con el mismo comando.
- ``dev``: ``HYPOTHESIS_PROFILE=dev`` busca a fondo (600 ejemplos, semilla
  aleatoria). Util antes de tocar tax_report_service, dca_signal_engine o
  valuation/currency.

Si Hypothesis no esta instalado (jobs que solo instalan requirements.txt),
la carpeta se ignora en vez de romper la recogida de tests.
"""

import os

try:
    from hypothesis import HealthCheck, settings
except ImportError:  # pragma: no cover - solo en jobs sin el extra `test`
    collect_ignore_glob = ["test_prop_*.py"]
else:
    settings.register_profile(
        "ci",
        max_examples=60,
        deadline=None,
        derandomize=True,
        suppress_health_check=[HealthCheck.too_slow],
        print_blob=True,
    )
    settings.register_profile(
        "dev",
        max_examples=600,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
        print_blob=True,
    )
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))
