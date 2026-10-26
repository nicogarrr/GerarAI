import re
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class SourceTier:
    key: str
    label: str
    rank: int
    trust_score: float
    policy: str


SOURCE_TIERS: dict[str, SourceTier] = {
    "tier_1_regulatory": SourceTier(
        key="tier_1_regulatory",
        label="Regulatory filing",
        rank=1,
        trust_score=1.0,
        policy="Primary regulatory evidence (SEC, CNMV, exchange/regulator of the issuer's market). Prefer this over vendor or media conflicts.",
    ),
    "tier_2_company": SourceTier(
        key="tier_2_company",
        label="Company primary",
        rank=2,
        trust_score=0.9,
        policy="Primary company evidence. Use for thesis updates, but reconcile against filings when numbers conflict.",
    ),
    "tier_3_transcript": SourceTier(
        key="tier_3_transcript",
        label="Transcript or call",
        rank=3,
        trust_score=0.82,
        policy="Management commentary. Treat forward-looking statements as claims until confirmed by results.",
    ),
    "tier_4_reputable_media": SourceTier(
        key="tier_4_reputable_media",
        label="Reputable media",
        rank=4,
        trust_score=0.72,
        policy="Useful alert source. Do not change model assumptions without primary-source confirmation.",
    ),
    "tier_5_data_provider": SourceTier(
        key="tier_5_data_provider",
        label="Data provider",
        rank=5,
        trust_score=0.68,
        policy="Useful normalized data. Reconcile important conflicts against the issuer's regulator and company primary sources.",
    ),
    "tier_6_bootstrap": SourceTier(
        key="tier_6_bootstrap",
        label="Bootstrap seed",
        rank=6,
        trust_score=0.45,
        policy="Startup data only. Replace with primary evidence before final thesis decisions.",
    ),
    "tier_7_user_input": SourceTier(
        key="tier_7_user_input",
        label="User input",
        rank=7,
        trust_score=0.38,
        policy="User-provided evidence or assumption. Keep it visible and confirm before material model changes.",
    ),
    "tier_unknown": SourceTier(
        key="tier_unknown",
        label="Unknown source",
        rank=99,
        trust_score=0.25,
        policy="Unknown reliability. Store as context only until source quality is established.",
    ),
}


SOURCE_TIER_BY_TYPE = {
    "sec": "tier_1_regulatory",
    "sec_edgar": "tier_1_regulatory",
    "edgar": "tier_1_regulatory",
    "filing": "tier_1_regulatory",
    "10-k": "tier_1_regulatory",
    "10-q": "tier_1_regulatory",
    "20-f": "tier_1_regulatory",
    "8-k": "tier_1_regulatory",
    "cnmv": "tier_1_regulatory",
    "fca": "tier_1_regulatory",
    "bafin": "tier_1_regulatory",
    "amf": "tier_1_regulatory",
    "consob": "tier_1_regulatory",
    "asic": "tier_1_regulatory",
    "jfsa": "tier_1_regulatory",
    "sedar": "tier_1_regulatory",
    "regulator": "tier_1_regulatory",
    "exchange_filing": "tier_1_regulatory",
    "company_ir": "tier_2_company",
    "investor_relations": "tier_2_company",
    "earnings_release": "tier_2_company",
    "shareholder_letter": "tier_2_company",
    "earnings_call": "tier_3_transcript",
    "transcript": "tier_3_transcript",
    "manual_transcript": "tier_3_transcript",
    "reuters": "tier_4_reputable_media",
    "bloomberg": "tier_4_reputable_media",
    "wsj": "tier_4_reputable_media",
    "ft": "tier_4_reputable_media",
    "fmp": "tier_5_data_provider",
    "finnhub": "tier_5_data_provider",
    "yahoo": "tier_5_data_provider",
    "company_master_seed": "tier_6_bootstrap",
    "seed": "tier_6_bootstrap",
    "manual": "tier_7_user_input",
    "manual_upload": "tier_7_user_input",
    "chat": "tier_7_user_input",
    "user": "tier_7_user_input",
}


def _host_matches(host: str, domain: str) -> bool:
    """El host ES el dominio o un subdominio suyo; nunca un sufijo mas largo.

    «sec.gov.evil.example» contiene la cadena «sec.gov» pero no es la SEC:
    la confianza de tier_1 nunca puede venir de una coincidencia de subcadena.
    """
    return host == domain or host.endswith("." + domain)


def _type_matches(key: str, compact_type: str, tokens: set[str]) -> bool:
    """Clave de tipo contra el tipo declarado.

    Claves de 4+ caracteres: subcadena (comportamiento historico, p. ej.
    «sec_edgar» o «10-k»). Claves de 2-3 («ft», «amf», «sec»...): solo token
    completo; como subcadena clasificarian «softbank» como Financial Times o
    «amfi» (India) como AMF (Francia).
    """
    if len(key) >= 4:
        return key in compact_type
    return key in tokens


_REGULATOR_DOMAINS = (
    "sec.gov",
    "cnmv.es",
    "fca.org.uk",
    "bafin.de",
    "amf-france.org",
    "consob.it",
    "asic.gov.au",
    "fsa.go.jp",
    "sedar.com",
)

_MEDIA_DOMAINS = {
    "reuters.com": "tier_4_reputable_media",
    "bloomberg.com": "tier_4_reputable_media",
    "wsj.com": "tier_4_reputable_media",
    "ft.com": "tier_4_reputable_media",
}


def classify_source(source_type: str | None = None, url: str | None = None) -> SourceTier:
    compact_type = (source_type or "").lower().replace(" ", "_")
    tokens = {token for token in re.split(r"[^a-z0-9]+", compact_type) if token}
    for key, tier_key in SOURCE_TIER_BY_TYPE.items():
        if _type_matches(key, compact_type, tokens):
            return SOURCE_TIERS[tier_key]

    compact_url = (url or "").strip().lower()
    if compact_url:
        parsed = urlparse(compact_url)
        host = parsed.hostname or ""
        if any(_host_matches(host, domain) for domain in _REGULATOR_DOMAINS):
            return SOURCE_TIERS["tier_1_regulatory"]
        if host.startswith("ir.") or "/investor" in parsed.path:
            return SOURCE_TIERS["tier_2_company"]
        for domain, tier_key in _MEDIA_DOMAINS.items():
            if _host_matches(host, domain):
                return SOURCE_TIERS[tier_key]

    return SOURCE_TIERS["tier_unknown"]


def source_tier_key(source_type: str | None = None, url: str | None = None) -> str:
    return classify_source(source_type, url).key
