import {
  E2E_ENABLED,
  E2E_SKIP_REASON,
  expect,
  jsonResponse,
  test,
  uniqueMarker,
} from "./fixtures/research-api";

type Claim = {
  id: number;
  statement: string;
  status: string;
};

type ThesisChange = {
  id: number;
  summary: string;
  materiality_score: number;
};

type ThesisVersion = {
  id: number;
  version: number;
  status: string;
};

type ThesisSection = {
  id: number;
  thesis_version_id: number;
  section_key: string;
  title: string;
  body: string;
  status: string;
};

test.skip(!E2E_ENABLED, E2E_SKIP_REASON);

test("thesis workspace create -> read (claim + change + sections)", async ({
  request,
}) => {
  const marker = uniqueMarker("e2e-thesis");

  // Create: claim como bloque de contenido de tesis, trazable por marker.
  const claim = await jsonResponse<Claim>(
    await request.post("/api/memory/claims", {
      data: {
        ticker: "MSFT",
        statement: `Azure AI demand remains a durable growth driver (${marker}).`,
        claim_type: "growth_driver",
        materiality_score: 8,
        source_quality: "primary",
      },
    }),
  );
  expect(claim.id).toBeGreaterThan(0);

  // Read: el claim vuelve con el mismo statement.
  const reread = await jsonResponse<Claim>(
    await request.get(`/api/memory/claims/${claim.id}`),
  );
  expect(reread.statement).toContain(marker);
  expect(reread.status).toBe("unverified");

  // Create: cambio de tesis con el mismo marker.
  const change = await jsonResponse<ThesisChange>(
    await request.post("/api/memory/thesis/changes", {
      data: {
        ticker: "MSFT",
        change_type: "manual",
        impact_direction: "positive",
        materiality_score: 6,
        summary: `Manual upside note for the durable thesis (${marker}).`,
        // El feed «Qué ha cambiado» descarta tarjetas sin relación con la
        // tesis (8644dd1): el cambio creado debe declarar su métrica.
        affected_metrics: ["revenue"],
      },
    }),
    200,
  );
  expect(change.id).toBeGreaterThan(0);

  // Read: el listado de cambios del ticker contiene el creado.
  const changes = await jsonResponse<ThesisChange[]>(
    await request.get("/api/memory/thesis/MSFT/changes"),
  );
  expect(changes).toContainEqual(
    expect.objectContaining({ id: change.id }),
  );

  // Frontera honesta: upsert de seccion sobre una version inexistente es 404.
  const versions = await jsonResponse<ThesisVersion[]>(
    await request.get("/api/thesis/MSFT/versions"),
  );
  if (versions.length === 0) {
    await jsonResponse(
      await request.post("/api/memory/thesis/MSFT/versions/999999999/sections", {
        data: {
          section_key: `note-${marker}`,
          title: `E2E note ${marker}`,
          body: "Sin tesis persistida no hay seccion que crear.",
        },
      }),
      404,
    );
  } else {
    // Update: upsert crea y re-upsert actualiza la misma section_key.
    const latest = versions[0];
    if (!latest) {
      throw new Error("Se esperaba al menos una version de tesis.");
    }
    const sectionKey = `e2e-note-${marker}`.slice(0, 80);
    const sectionUrl = `/api/memory/thesis/MSFT/versions/${latest.id}/sections`;
    const createdSection = await jsonResponse<ThesisSection>(
      await request.post(sectionUrl, {
        data: {
          section_key: sectionKey,
          title: `E2E note ${marker}`,
          body: `First body ${marker}.`,
        },
      }),
    );
    const updatedSection = await jsonResponse<ThesisSection>(
      await request.post(sectionUrl, {
        data: {
          section_key: sectionKey,
          title: `E2E note ${marker}`,
          body: `Updated body ${marker}.`,
        },
      }),
    );
    expect(updatedSection.id).toBe(createdSection.id);
    expect(updatedSection.body).toContain(`Updated body ${marker}`);

    const sections = await jsonResponse<ThesisSection[]>(
      await request.get("/api/memory/thesis/MSFT/sections"),
    );
    expect(sections).toContainEqual(
      expect.objectContaining({
        id: updatedSection.id,
        body: expect.stringContaining(marker),
      }),
    );
  }

  // Limpieza: claims/changes no exponen DELETE en la API; las filas quedan
  // marcadas con el marker unico del run (inertes, sin efecto en otros runs).
  // Las reglas de alerta del otro spec si se desactivan (ver investor-alert-crud).
});
