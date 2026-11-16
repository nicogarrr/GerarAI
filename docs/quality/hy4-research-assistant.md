# Hy4: Cerebro guia por ticker

PR separada, apilada sobre guard de #5756 (4d435fed).
POST /api/research/assistant acepta model opcional literal hy4-flash-free.
Ausente conserva proveedor anterior. Presente inyecta proveedor dedicado Go,
con contexto que bloquea transporte de otros modelos/endpoints. Baseline,
citas exactas y validadores financieros se conservan. Ante corte coste/precio
no se oculta el aviso: se anade al baseline y missing_data.
No modifica seleccion global ni ejecuta lotes; no activa ExtraUsage.
Los limites economicos y de latch son los de #5756. OFF declarado por Nico,
no verificado API; FAV y despliegue por Piloto siguen siendo necesarios.
Tests locales: bateria assistant+Hy4, archivo ruta >=85% lineas y ramas.
Frontend debe enviar el mismo campo model del chat general en esta ruta.
