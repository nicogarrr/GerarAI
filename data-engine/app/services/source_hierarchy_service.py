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
    "tier_8_social": SourceTier(
        key="tier_8_social",
        label="Social media (unverified)",
        rank=8,
        trust_score=0.05,
        policy="Social chatter, unverified. Context only: never feeds alerts, "
        "story clusters, verified-source counts or materiality.",
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
    "social conversation": "tier_8_social",
    # Medios financieros y agregadores habituales en la ingesta real (vía RSS
    # de Google News la URL es news.google.com, así que la cadena de la fuente
    # es la única señal). Auditoría 28-oct-2026: el 59 % de los eventos en
    # prod caía en tier_unknown (trust 0,25) con MarketBeat, Seeking Alpha o
    # Stock Titan indistinguibles de un blog anónimo.
    "pr newswire": "tier_5_data_provider",
    "prnewswire": "tier_5_data_provider",
    "business wire": "tier_5_data_provider",
    "businesswire": "tier_5_data_provider",
    "globenewswire": "tier_5_data_provider",
    "globe newswire": "tier_5_data_provider",
    "accesswire": "tier_5_data_provider",
    "access newswire": "tier_5_data_provider",
    "stock titan": "tier_5_data_provider",
    "stocktitan": "tier_5_data_provider",
    "marketbeat": "tier_5_data_provider",
    "seeking alpha": "tier_5_data_provider",
    "simply wall street": "tier_5_data_provider",
    "simply wall st": "tier_5_data_provider",
    "tradingview": "tier_5_data_provider",
    "zacks": "tier_5_data_provider",
    "benzinga": "tier_5_data_provider",
    "tipranks": "tier_5_data_provider",
    "investing": "tier_5_data_provider",
    "marketscreener": "tier_5_data_provider",
    "gurufocus": "tier_5_data_provider",
    "motley fool": "tier_5_data_provider",
    "fool.com": "tier_5_data_provider",
    "24/7 wall st": "tier_5_data_provider",
    "barchart": "tier_5_data_provider",
    "quiver quantitative": "tier_5_data_provider",
    "biggo finance": "tier_5_data_provider",
    "streetinsider": "tier_5_data_provider",
    "trefis": "tier_5_data_provider",
    "the fast mode": "tier_5_data_provider",
    "finanzas, bolsa y forex": "tier_5_data_provider",
    "forbes": "tier_5_data_provider",
    "business insider": "tier_5_data_provider",
    "ars technica": "tier_5_data_provider",
    "techrepublic": "tier_5_data_provider",
    "bgr": "tier_5_data_provider",
    # Prensa sectorial (teleco/espacio) habitual en el carril ASTS.
    "telecompaper": "tier_5_data_provider",
    "telecompetitor": "tier_5_data_provider",
    "telesemana": "tier_5_data_provider",
    "dpl news": "tier_5_data_provider",
    "developing telecoms": "tier_5_data_provider",
    "advanced television": "tier_5_data_provider",
    "eenews": "tier_5_data_provider",
    "light reading": "tier_5_data_provider",
    "satnews publishers": "tier_5_data_provider",
    "satellitepro me": "tier_5_data_provider",
    "space & defense": "tier_5_data_provider",
    "aviation week": "tier_5_data_provider",
    "crowdfund insider": "tier_5_data_provider",
    # Medios generalistas de referencia.
    "financial times": "tier_4_reputable_media",
    "barron's": "tier_4_reputable_media",
    "morningstar": "tier_4_reputable_media",
    "the globe and mail": "tier_4_reputable_media",
    "nbc news": "tier_4_reputable_media",
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


def _type_matches(key: str, tokens: list[str]) -> bool:
    """La clave casa como secuencia CONTIGUA de tokens del tipo declarado.

    Nunca subcadena: «asic» no casa «basic», «ft» no casa «softbank», «amf»
    no casa «amfi» (India). Las claves compuestas casan por sus propios
    tokens: «sec_edgar» -> [sec, edgar], «8-k» -> [8, k] (el guion no mata
    la clave), «manual_transcript» -> [manual, transcript].
    """
    key_tokens = [token for token in re.split(r"[^a-z0-9]+", key) if token]
    if not key_tokens:
        return False
    size = len(key_tokens)
    return any(tokens[i : i + size] == key_tokens for i in range(len(tokens) - size + 1))


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
    tokens = [token for token in re.split(r"[^a-z0-9]+", compact_type) if token]
    for key, tier_key in SOURCE_TIER_BY_TYPE.items():
        if _type_matches(key, tokens):
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
