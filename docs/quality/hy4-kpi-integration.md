# Hy4 KPI integration

Depende del reemplazo temporal comun9d6c6b88. La factory sirveHy4cuando
HY4_REPLACE_DEEPSEEK=1. Esta PR prueba y cierra ruta KPI real:
KPIExtractionService.extract_document -> unico provider.complete por documento.
Con Hy4 no usa Jev (posible micromodelo ajeno), no solicita presupuesto heuristico
positivo ni registra precio inventado: el provider valida billing0 antesde
retornar; gasto app0. Cuota diaria existente sigue reservandointento.
Deterministic-only o metricas ya cubiertas siguen sinLMM. 429/402 propagan
sinreintento (1intento probado), candidatos solo pendingapproval y nunca
canonicos por mera respuesta. Aprobacion/normalizacion/citas/N-Dintactos.
No haylotes ni inferenciareal nueva. Ensayo productivoposterior1docpublico
acotado, stopprimererror402/429/coste, FAVSHAexactoantesmerge/deployPiloto.
Tests148verdes; kpi_extraction_service.py95,03%lineas85,71%ramas.
