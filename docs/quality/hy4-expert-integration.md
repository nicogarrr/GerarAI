# Hy4: equipo de expertos

Depende de reemplazo temporalcomun9d6c6b88. provider_reasoner usado por equipo y
thesis_v2 recibeHy4 via factory. Con Hy4 serializa las llamadas del reasoner,
maximo3intentosporcorrida inicial (incluye juez); resto quedan comoerrorrotulado,
no afirmacion verificada. Un402/429 o ProviderDisabledError(corteHy4) cierra
esa corrida antes de otra llamada. Otra corrida no comparte ese latch; el
provider mantiene ademas su guard proceso/precio/coste. Sinfallback aotroLLM.
Costeapp0 solo paraHy4validado por provider; los otros conservan presupuesto.
Evidencia puede reunirse concurrentemente, no supone inferenceconcurrente.
No se alteran calculos ni fuentes ni se convierten claims sin validar enfacts.
27testsunitarios/integracionpipelineverdes,service.py100%lineas88,46%ramas.
Suite chat experto conSQLite se comprueba por separado; si falla se informa,
no sustituye gateCIcompleto. No inferencias reales ni lotes en estaPR.
