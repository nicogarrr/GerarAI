"""Los avisos DCA salen apagados y sin correo salvo configuracion explicita."""
from app.core.config import Settings
from app.services import dca_signal_service as dca


def _fresh() -> Settings:
    return Settings(_env_file=None)


def test_dca_alerts_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DCA_ALERTS_ENABLED", raising=False)
    assert _fresh().dca_alerts_enabled is False


def test_dca_default_channels_have_no_email(monkeypatch):
    monkeypatch.delenv("DCA_ALERT_CHANNELS", raising=False)
    settings = _fresh()
    assert settings.dca_alert_channels == "in_app"
    assert "email" not in dca.alert_channels(settings)


def test_dca_alerts_still_enable_with_explicit_env(monkeypatch):
    monkeypatch.setenv("DCA_ALERTS_ENABLED", "true")
    monkeypatch.setenv("DCA_ALERT_CHANNELS", "in_app,email")
    settings = _fresh()
    assert settings.dca_alerts_enabled is True
    assert dca.alert_channels(settings) == ["in_app", "email"]
