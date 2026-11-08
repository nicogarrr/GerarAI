"""Textos de los avisos de próximos resultados (earnings_alert_copy): módulo
puro sin tests directos. Se fija: ventanas, idiomas, estado de la fecha sin
inventar, filas condicionales (solo se pinta lo que existe) y escape HTML."""

from app.services.dca_alert_copy import short_date
from app.services.display_es import fecha_es
from app.services.earnings_alert_copy import (
    DISCLAIMER,
    DISCLAIMER_EN,
    confirmation_text,
    detail_rows,
    email_content,
    message_text,
    title,
    when_text,
)

BASE = {
    "ticker": "KO",
    "company_name": "Coca-Cola",
    "event_date": "2026-11-03",
    "window": "week",
    "session": "pre_market",
    "confirmed": True,
    "fiscal_label": "Sep/2026",
    "origin": "cartera",
    "source": "Nasdaq",
    "source_url": "https://example.com/ko",
}


class TestWhenText:
    def test_ventanas_en_espanol(self):
        assert when_text({**BASE, "window": "today"}) == "hoy"
        assert when_text({**BASE, "window": "day"}) == "mañana"
        assert when_text({**BASE, "window": "week"}) == f"el {fecha_es('2026-11-03')}"

    def test_ventanas_en_ingles(self):
        assert when_text({**BASE, "window": "today"}, "en") == "today"
        assert when_text({**BASE, "window": "day"}, "en") == "tomorrow"
        assert when_text({**BASE, "window": "week"}, "en") == f"on {short_date('2026-11-03', 'en')}"


class TestTitle:
    def test_espanol(self):
        assert title({**BASE, "window": "today"}) == "KO presenta resultados hoy"

    def test_ingles(self):
        assert title({**BASE, "window": "today"}, "en") == "KO reports earnings today"


class TestConfirmationText:
    def test_confirmada_estimada_o_desconocida_sin_inventar(self):
        assert confirmation_text({**BASE, "confirmed": True}) == "Fecha confirmada por la fuente"
        assert (
            confirmation_text({**BASE, "confirmed": False}) == "Fecha estimada por la fuente; puede cambiar"
        )
        assert confirmation_text({k: v for k, v in BASE.items() if k != "confirmed"}) == (
            "La fuente no indica si la fecha esta confirmada"
        )

    def test_ingles(self):
        assert confirmation_text({**BASE, "confirmed": True}, "en") == "Date confirmed by the source"
        assert (
            confirmation_text({**BASE, "confirmed": False}, "en")
            == "Date estimated by the source; it may change"
        )
        assert confirmation_text({k: v for k, v in BASE.items() if k != "confirmed"}, "en") == (
            "The source does not say whether the date is confirmed"
        )


class TestDetailRows:
    def test_solo_se_pinta_lo_que_existe(self):
        labels = [label for label, _ in detail_rows(BASE)]
        assert labels == [
            "Fecha",
            "Franja",
            "Estado de la fecha",
            "Trimestre comunicado",
            "Origen del seguimiento",
            "Fuente",
        ]

    def test_minimo_solo_fecha_y_estado(self):
        rows = detail_rows({"ticker": "KO", "event_date": "2026-11-03", "confirmed": None})
        assert [label for label, _ in rows] == ["Fecha", "Estado de la fecha"]

    def test_franja_desconocida_no_se_pinta(self):
        labels = [label for label, _ in detail_rows({**BASE, "session": "mid_day"})]
        assert "Franja" not in labels

    def test_la_franja_nunca_lleva_hora_inventada(self):
        rows = dict(detail_rows(BASE))
        assert rows["Franja"] == "antes de la apertura (franja publicada por la fuente; sin hora exacta)"

    def test_etiquetas_en_ingles(self):
        labels = [label for label, _ in detail_rows(BASE, "en")]
        assert labels == ["Date", "Session", "Date status", "Reported quarter", "Tracked from", "Source"]
        rows = dict(detail_rows(BASE, "en"))
        assert rows["Tracked from"] == "Your portfolio"


class TestMessageText:
    def test_estructura_completa(self):
        text = message_text(BASE)
        lines = text.split("\n")
        assert lines[0] == "KO presenta resultados el " + fecha_es("2026-11-03")
        assert lines[1] == "Coca-Cola"
        assert "Fuente: Nasdaq" in text
        assert "Enlace de la fuente: https://example.com/ko" in text
        assert lines[-1] == DISCLAIMER

    def test_sin_nombre_ni_enlace_no_se_pintan(self):
        data = {k: v for k, v in BASE.items() if k not in ("company_name", "source_url")}
        text = message_text(data)
        assert "Coca-Cola" not in text
        assert "Enlace de la fuente" not in text

    def test_ingles(self):
        text = message_text(BASE, "en")
        assert text.split("\n")[0] == "KO reports earnings on " + short_date("2026-11-03", "en")
        assert "Source link: https://example.com/ko" in text
        assert text.split("\n")[-1] == DISCLAIMER_EN


class TestEmailContent:
    def test_subject_con_empresa_y_texto_igual_al_mensaje(self):
        email = email_content(BASE)
        assert email.subject == "KO presenta resultados el " + fecha_es("2026-11-03") + " · Coca-Cola"
        assert email.text == message_text(BASE)

    def test_subject_sin_empresa_y_tope_250(self):
        email = email_content({k: v for k, v in BASE.items() if k != "company_name"})
        assert "·" not in email.subject
        largo = email_content({**BASE, "company_name": "X" * 400})
        assert len(largo.subject) <= 250

    def test_html_idioma_y_escape(self):
        email = email_content({**BASE, "company_name": "<script>alert(1)</script>"})
        assert email.html is not None
        assert '<html lang="es">' in email.html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in email.html
        assert "<script>alert(1)</script>" not in email.html
        email_en = email_content(BASE, "en")
        assert email_en.html is not None
        assert '<html lang="en">' in email_en.html

    def test_html_escapa_la_url_de_la_fuente(self):
        email = email_content({**BASE, "source_url": 'https://example.com/?a=" onclick="x'})
        assert email.html is not None
        assert 'href="https://example.com/?a=&quot; onclick=&quot;x"' in email.html
