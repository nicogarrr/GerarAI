"""StoryClusterIndex: mismas agrupaciones que el recorrido lineal (find_group),
con coste ~lineal en escaneos profundos de portada."""

import random
import time
from datetime import UTC, datetime, timedelta

from app.models.entities import NewsEvent
from app.services.news_headline_translation import original_headline
from app.services.news_story_cluster import (
    StoryClusterIndex,
    StoryGroup,
    absorb,
    event_signature,
    exact_key,
    find_group,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
WORDS = ["tesla", "nvda", "apple", "bonds", "yields", "inflation", "fed", "oil", "china", "merger", "lawsuit", "earnings", "chip", "rally", "slump", "guidance", "dividend", "buyback", "stake", "outlook", "profit", "quarter"]


def _event(i: int, title: str, *, lane: str | None = None, minutes: int = 30, company_id=None, metadata=None):
    md = {"connector": "rss", "date_source": "source"}
    if lane:
        md["news_lane"] = lane
    if metadata:
        md.update(metadata)
    return NewsEvent(
        tenant_id=1,
        company_id=company_id,
        title=title,
        source="rss",
        url=f"https://example.com/{i}",
        date=NOW - timedelta(minutes=minutes * i),
        metadata_=md,
    )


def _naive(events):
    """Agrupación con la lista plana (algoritmo anterior)."""
    groups: list[StoryGroup] = []
    for ev in events:
        sig = event_signature(ev, None)
        group = find_group(groups, ev, None, sig)
        if group is not None:
            absorb(group, ev)
            continue
        groups.append(StoryGroup(event=ev, company=None, signature=sig, text_key=exact_key(original_headline(ev))))
    return [(g.event.url, len(g.coverage)) for g in groups]


def _indexed(events):
    idx = StoryClusterIndex()
    for ev in events:
        sig = event_signature(ev, None)
        group = idx.find(ev, None, sig)
        if group is not None:
            absorb(group, ev)
            continue
        idx.add(StoryGroup(event=ev, company=None, signature=sig, text_key=exact_key(original_headline(ev))))
    return [(g.event.url, len(g.coverage)) for g in idx.groups]


def test_index_matches_naive_on_random_feeds():
    rng = random.Random(20261102)
    for seed in range(6):
        rnd = random.Random(seed)
        events = []
        for i in range(160):
            kind = rnd.random()
            if kind < 0.25 and events:
                # misma historia reescrita: comparte la mayoría de tokens
                prev = rnd.choice(events)
                title = prev.title + " actualización"
            elif kind < 0.4 and events:
                # titular literal repetido (dedup exacto)
                title = rnd.choice(events).title
            elif kind < 0.5:
                # solo stopwords/empresa: firma vacía
                title = "the and of"
            else:
                title = " ".join(rnd.sample(WORDS, 5) + [f"token{rnd.randint(0, 9999)}"])
            lane = rnd.choice([None, None, "macro"])
            events.append(_event(i, title, lane=lane, minutes=rnd.choice([5, 30, 3000])))
        assert _indexed(events) == _naive(events), f"seed {seed}"
    rng.random()  # silencia linters sobre rng sin uso


def test_literal_match_keeps_first_group_even_with_story_candidates():
    # A y B comparten firma pero quedaron en grupos separados por la ventana de
    # 48 h. El evento nuevo: misma historia que A (dentro de ventana) y titular
    # literal de B. El recorrido lineal absorbe en A (el primero insertado que
    # casa); el índice debe devolver el mismo grupo, no el literal más cómodo.
    events = [
        _event(0, "fed recorta tipos tokena empresaa caso", minutes=1),          # t0
        _event(1, "fed recorta tipos tokena empresaa informe", minutes=61 * 60), # t0 + 61 h: fuera de ventana
    ]
    new = NewsEvent(
        tenant_id=1, company_id=None, title="fed recorta tipos tokena empresaa informe",
        source="rss", url="https://example.com/nuevo", date=NOW - timedelta(minutes=90),
        metadata_={"connector": "rss", "date_source": "source"},
    )
    naive_groups = []
    idx = StoryClusterIndex()
    for ev in events + [new]:
        sig = event_signature(ev, None)
        group = find_group(naive_groups, ev, None, sig)
        if group is not None:
            absorb(group, ev)
        else:
            naive_groups.append(StoryGroup(event=ev, company=None, signature=sig, text_key=exact_key(original_headline(ev))))
        found = idx.find(ev, None, sig)
        if found is not None:
            absorb(found, ev)
        else:
            idx.add(StoryGroup(event=ev, company=None, signature=sig, text_key=exact_key(original_headline(ev))))
    assert [(g.event.url, len(g.coverage)) for g in idx.groups] == [
        (g.event.url, len(g.coverage)) for g in naive_groups
    ]
    assert len(idx.groups) == 2
    assert idx.groups[0].coverage and idx.groups[0].coverage[0]["url"] == "https://example.com/nuevo"
    assert idx.groups[1].coverage == []


def test_deep_scan_cost_stays_near_linear():
    # Vocabulario realista: palabras financieras comunes compartidas entre
    # titulares + tokens únicos por historia, 15% de reescrituras.
    common = [f"common{i}" for i in range(500)]
    rnd = random.Random(11)

    def headline(i):
        toks = rnd.sample(common, 4) + [f"hist{i}x{j}" for j in range(rnd.randint(2, 5))]
        rnd.shuffle(toks)
        return " ".join(toks)

    titles = []
    for i in range(2000):
        if titles and rnd.random() < 0.15:
            titles.append(rnd.choice(titles) + f" update{i}")
        else:
            titles.append(headline(i))
    events = [_event(i, title, minutes=17) for i, title in enumerate(titles)]
    start = time.perf_counter()
    result = _indexed(events)
    elapsed_ms = (time.perf_counter() - start) * 1000
    # Lista plana medida con ESTE mismo generador (lab, 2026-11-02): 979,0 ms.
    # Índice: 107,2 ms (-89%). Cota holgada para CI lento.
    assert elapsed_ms < 400, f"escaneo profundo {elapsed_ms:.1f} ms"
    assert len(result) > 1500
