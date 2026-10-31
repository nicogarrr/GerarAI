from app.services.text_clip import clip_words, normalize_scraped_text


def test_short_text_returned_as_is():
    assert clip_words("hola mundo", 20) == "hola mundo"


def test_cuts_at_last_full_word():
    assert clip_words("uno dos tres cuatro", 10) == "uno dos…"
    assert clip_words("uno dos tres cuatro", 7) == "uno dos…"


def test_single_giant_word_cuts_at_limit():
    assert clip_words("abcdefghij", 5) == "abcde…"


def test_complete_last_word_is_kept():
    assert clip_words("uno dos tres", 8) == "uno dos…"


def test_thesis_news_summary_does_not_cut_mid_word():
    text = "La empresa presentó resultados del tercer trimestre"
    assert clip_words(text, 40) == "La empresa presentó resultados del…"


def test_normalize_scraped_text_repara_casos_html_observados():
    raw = "…StockCurrent Price: $210. 32Target Price (Mid): ~$794Street Target:…What Happened?Coherent (COHR:NYSE) fell 11."
    out = normalize_scraped_text(raw)
    assert "Stock Current Price" in out
    assert "$210.32 Target Price" in out
    assert "~$794 Street Target" in out
    assert "What Happened? Coherent" in out
    assert "fell 11." in out


def test_normalize_scraped_text_doble_punto():
    assert normalize_scraped_text("(2025-12-31:FY)..") == "(2025-12-31:FY)."
    # La elipsis legítima no se toca.
    assert normalize_scraped_text("texto… sigue") == "texto… sigue"
    assert normalize_scraped_text("espera... luego") == "espera... luego"


def test_normalize_no_toca_nombres_camelcase():
    # Sin heurística camelCase general: los nombres pegados reales quedan
    # intactos; solo se separan cadenas exactas observadas (StockCurrent).
    for marca in ("iPhone", "eBay", "FedEx", "ExxonMobil", "BlackRock",
                  "McDonalds", "JPMorgan", "YouTube", "WhatsApp",
                  "SpaceMobile", "UnitedHealth", "ServiceNow"):
        assert normalize_scraped_text(marca) == marca, marca
    texto = "Apple presenta el iPhone y eBay sube; UnitedHealth baja un 2 % y ServiceNow un 1 %."
    assert normalize_scraped_text(texto) == texto
    assert normalize_scraped_text("StockCurrent Price") == "Stock Current Price"


def test_normalize_no_toca_tickers():
    for ticker in ("COHR:NYSE", "3M", "B2B", "AAPL", "S&P500"):
        assert normalize_scraped_text(ticker) == ticker, ticker


def test_normalize_no_toca_decimales_es():
    assert normalize_scraped_text("1, 23") == "1, 23"
    assert normalize_scraped_text("cae un 3,5 % tras resultados") == "cae un 3,5 % tras resultados"
    assert normalize_scraped_text("1.234,56") == "1.234,56"


def test_normalize_no_rompe_texto_sano():
    sano = "Apple (AAPL) cae un 3,5 % tras resultados del Q4 2026."
    assert normalize_scraped_text(sano) == sano
    assert normalize_scraped_text("") == ""
    assert normalize_scraped_text(None) == ""
