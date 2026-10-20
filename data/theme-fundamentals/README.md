# Instantáneas públicas revisadas

Son datos fechados, no un feed en vivo. En cada serie se muestran unidad,
fuente, publicación, vintage y fecha de revisión. Actualización manual con PR
para revisar cambios de esquema y unidades antes de publicar. El pipeline no
extrae de UxC ni Cameco.

Nuclear: `python scripts/theme-fundamentals/import_eia.py` (openpyxl).
Después, conservar/revisar el contexto NEA/IAEA del JSON: no se actualiza con
los datos EIA. EIA: tablas XLS 11, 12, 7 y producción trimestral tabla 1.
El HTML puede estar en una edición anterior al XLS. W y ausencias son null.
No deducir valores suprimidos, ni combinar vintages, ni convertirlos en cero.

Contexto mundial: OECD/NEA e IAEA, Uranium 2024 (publicado 2025), licencia
CC BY 4.0 con excepciones de material de terceros. Base estadística principal
2021/2022. Escenarios 2050 atribuidos y separados de datos históricos.

No hay refresco automático comprometido; la fecha de revisión evita aparentar
actualidad. Sin una revisión nueva, continúa visible la instantánea fechada.
