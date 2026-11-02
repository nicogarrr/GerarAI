# SUBTEL official decree evidence

Free primary source, no paid provider or API key. The daily job checks the known
AST SpaceMobile Chile application (SI, request10872,28January2026), not every
application in Chile. It does not claim a complete regulatory news feed.

Verified on2November2026:
- Register: https://publico.subtel.gob.cl/data-externa/getSolicitudes?tipoServicio=SI&fechaDesde=28%2F01%2F2026&fechaHasta=28%2F01%2F2026
- Official PDF: https://publico.subtel.gob.cl/dwldDocSubtel/view?rutaArchivo=/ofpartes/Decretos/Exentos/2026/26de_1209.pdf

The register links the same document under tramites.subtel.gob.cl (404 at
verification). The connector only rewrites that exact download host to its
verified public alias. Arbitrary URLs, other paths, redirects and responses
above5MB are rejected. Issuer and request must also match in the actual PDF.
HTML and PDF fixtures are copies from these sources, not social screenshots.

Decree1209/2026 is signed15October2026. The PDF authorizes transport/Servicio
Intermedio, NGSO SpaceMobile, uplink1990–2010MHz, downlink2170–2200MHz.
Thirty-year duration and18/22/24-month construction/service deadlines run from
Diario Oficial publication. Publication date is UNVERIFIED, not October15 by
assumption. The event date explicitly means decree date, not publication or
commercial launch. Detailed original text/hash/provenance remains attached.

The scheduled actor fetches globally once daily, then persists separate tenant
copies. It never changes thesis or portfolio records and creates no alerts.
Idempotence is by tenant+source+official PDF URL under the coalesced actor.
No migration or paid dependencies are added; pypdf already exists in the project.

Validation:13 SUBTEL tests plus4 existing RSS budget tests pass;2814 repository
guards pass. Tests cover real fixtures, identity/dates, foreign URLs/paths,
redirect/size/content rejection, tenant isolation/idempotence, no thesis/alert
flags, and partial actor failure cleanup. Ruff clean. Live ingestion awaits
deployment; a merged connector is not evidence the event has entered production.
