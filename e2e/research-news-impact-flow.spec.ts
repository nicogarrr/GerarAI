import {
  E2E_ENABLED,
  E2E_SKIP_REASON,
  expect,
  jsonResponse,
  test,
  uniqueMarker,
} from "./fixtures/research-api";

type NewsAssessment = {
  ticker: string | null;
  materiality_score: number;
  impact_direction: string;
  requires_update: boolean;
  affected_assumptions: string[];
};

type NewsIngestResponse = {
  status: string;
  received: number;
  created: number;
  skipped_duplicates: number;
  requires_update: number;
  events: NewsAssessment[];
};

type NewsEvent = {
  ticker: string | null;
  url: string | null;
  materiality_score: number;
  impact_direction: string;
  requires_update: boolean;
};

type ThesisChange = {
  change_type: string;
  impact_direction: string;
  materiality_score: number;
  summary: string;
  affected_metrics: string[];
  requires_review: boolean;
};

test.skip(!E2E_ENABLED, E2E_SKIP_REASON);

test("news -> materiality -> thesis change", async ({ request }) => {
  const marker = uniqueMarker("e2e-news");
  const url = `https://www.sec.gov/Archives/${marker}`;
  const item = {
    ticker: "MSFT",
    title: `Microsoft cuts guidance after earnings miss ${marker}`,
    text:
      "Microsoft disclosed an SEC fraud investigation, a share offering with dilution, " +
      "and lower revenue and FCF margin guidance.",
    url,
    source: "sec_filing",
  };

  const ingestion = await jsonResponse<NewsIngestResponse>(
    await request.post("/api/news/ingest", {
      data: {
        source: "sec_filing",
        items: [item, item],
      },
    }),
  );

  expect(ingestion).toMatchObject({
    status: "ingested",
    received: 2,
    created: 1,
    skipped_duplicates: 1,
    requires_update: 1,
  });
  expect(ingestion.events[0]).toMatchObject({
    ticker: "MSFT",
    materiality_score: 10,
    impact_direction: "negative",
    requires_update: true,
  });
  expect(ingestion.events[0]?.affected_assumptions).toEqual(
    expect.arrayContaining(["guidance", "revenue_growth", "fcf_margin", "dilution_risk"]),
  );

  const news = await jsonResponse<NewsEvent[]>(await request.get("/api/news"));
  expect(news).toContainEqual(
    expect.objectContaining({
      ticker: "MSFT",
      url,
      materiality_score: 10,
      impact_direction: "negative",
      requires_update: true,
    }),
  );

  const changes = await jsonResponse<ThesisChange[]>(
    await request.get("/api/memory/thesis/MSFT/changes"),
  );
  const change = changes.find((candidate) => candidate.summary.includes(marker));
  expect(change).toMatchObject({
    change_type: "news_potential_invalidation",
    impact_direction: "negative",
    materiality_score: 10,
    requires_review: true,
  });
  expect(change?.affected_metrics).toEqual(
    expect.arrayContaining(["guidance", "revenue_growth", "fcf_margin", "dilution_risk"]),
  );
});
