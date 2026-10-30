"""Reglas propias de .gitleaks.toml para lo que las reglas por defecto no ven.

En el historial quedaron una contrasena de MongoDB Atlas dentro de una URI y un
BETTER_AUTH_SECRET real; gitleaks con sus reglas por defecto no marco ninguno
(docs/ROTACION_CLAVES.md). Este test emula las reglas propias (regex, grupo,
entropia y allowlists) para que una edicion del TOML no las deje ciegas ni
empiece a bloquear PRs por marcadores de documentacion o secretos de CI.

Los ejemplos se construyen concatenando trozos para que este fichero no sea
a su vez un hallazgo de gitleaks.
"""

from __future__ import annotations

import math
import re
import tomllib
from collections import Counter
from pathlib import Path

import pytest

CONFIG = Path(__file__).resolve().parents[2] / ".gitleaks.toml"


def _rules() -> dict[str, dict]:
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    return {rule["id"]: rule for rule in data.get("rules", [])}


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _finds(rule: dict, line: str) -> bool:
    for match in re.finditer(rule["regex"], line):
        secret = match.group(rule.get("secretGroup", 0))
        if rule.get("entropy") and _entropy(secret) < rule["entropy"]:
            continue
        allowed = False
        for allow in rule.get("allowlists", []):
            target = match.group(0) if allow.get("regexTarget") == "match" else secret
            if any(re.search(rx, target) for rx in allow.get("regexes", [])):
                allowed = True
        if not allowed:
            return True
    return False


MONGO = "mongodb" + "+srv://"
REALISH_PW = "Q7m" + "x2Lp9" + "Vt4Rk8"
REALISH_SECRET = "k3J9" + "vQ2mZ8" + "xR7tB1" + "nW5yH4" + "cL6pD0" + "fG2sA9" + "eU3iO7=="


def test_custom_rules_exist() -> None:
    rules = _rules()
    assert "mongodb-uri-with-password" in rules
    assert "better-auth-secret-assignment" in rules


@pytest.mark.parametrize(
    "line",
    [
        f"MONGODB_URI={MONGO}gerarai:{REALISH_PW}@cluster0.ab12cd.mongodb.net/app",
        f"    {MONGO}admin:{REALISH_PW}@jlcluster.x1y2z3.mongodb.net/?retryWrites=true",
    ],
)
def test_mongodb_uri_with_real_password_is_caught(line: str) -> None:
    assert _finds(_rules()["mongodb-uri-with-password"], line)


@pytest.mark.parametrize(
    "line",
    [
        f"MONGODB_URI={MONGO}usuario:password@cluster.mongodb.net/app",
        f"MONGODB_URI={MONGO}user:<password>@cluster.mongodb.net/app",
        f"MONGODB_URI={MONGO}user:" + "${MONGO_PASSWORD}" + "@cluster.mongodb.net",
        "MONGODB_URI=mongodb://" + "root:" + REALISH_PW + "@localhost:27017/app",
        "MONGODB_URI=mongodb://" + "root:" + REALISH_PW + "@mongo:27017/app",
        "MONGODB_URI=mongodb://localhost:27017/app",
    ],
)
def test_mongodb_placeholders_and_local_services_pass(line: str) -> None:
    assert not _finds(_rules()["mongodb-uri-with-password"], line)


def test_real_better_auth_secret_is_caught() -> None:
    assert _finds(_rules()["better-auth-secret-assignment"], "BETTER_AUTH_SECRET=" + REALISH_SECRET)
    assert _finds(_rules()["better-auth-secret-assignment"], "  BETTER_AUTH_SECRET: '" + REALISH_SECRET + "'")


@pytest.mark.parametrize(
    "value",
    [
        "ci-only-better-auth-secret-not-for-production-0001",
        "genera-uno-con-openssl-rand-base64-32-aqui",
        "e2e-local-better-auth-secret-value-for-playwright",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "${BETTER_AUTH_SECRET}",
    ],
)
def test_ci_and_placeholder_better_auth_values_pass(value: str) -> None:
    assert not _finds(_rules()["better-auth-secret-assignment"], "BETTER_AUTH_SECRET=" + value)
