"""Generador del fichero del Modelo 720 (declaración informativa, bienes en
el extranjero).

Diseño de registro verificado contra la especificación OFICIAL de AEAT:
"Modelo 720. Diseños físicos y lógicos para la presentación telemática"
(sede.agenciatributaria.gob.es, DR_Resto_Mod/archivos/modelo_720.pdf).
Registros de 500 bytes, ISO-8859-1, numéricos ajustados a la derecha con
ceros, alfanuméricos a la izquierda con blancos, en mayúsculas sin acentos.

Enfoque de referencia: DeclaRenta (GPL-3.0) — solo como guía de dominio.
Su layout tiene discrepancias con la spec oficial (valoraciones 13+2 en vez
de 12+2, subclave vacía, valor de adquisición en valoración 1 para clave V,
ID de cuenta en posiciones de ISIN); aquí se implementa el layout OFICIAL,
sin copia de código.

Honestidad (sin verde falso), dictamen del auditor incorporado:
- Sin NIF, apellidos y nombre, número de declaración (13 dígitos que
  comienzan por 720) o país de depósito de los valores no se genera
  fichero: ``available=false``. Ningún dato material se inventa.
- El país del registro de valores (posiciones 129-130) es donde los
  valores están DEPOSITADOS O GESTIONADOS, no el emisor del ISIN: se toma
  de ``tax_declarant.custody_country``, nunca del prefijo del ISIN.
- La fecha de incorporación (415-422) es obligatoria por ISIN
  (``first_acquisition_dates``); sin ella, available=false. Un ISIN
  comprado en lotes con fechas distintas requiere registros separados:
  se genera UN registro con la fecha aportada y se avisa en ``notas``.
- Origen: siempre "A" (nueva declaración). El origen "M" exige verificar
  un incremento conjunto >20.000 € contra la última declaración, dato que
  no tenemos: los ISINs ya declarados van a ``manual_review``.
- Bajas: sin fecha EFECTIVA de extinción no se genera registro de baja
  (inventar 31/12 sería un dato falso); los ISINs de la declaración
  anterior ya no poseídos van a ``manual_review``.
- Cuentas (clave C) NO se generan: exigen identificador de cuenta
  asignado por la entidad, identidad real de la entidad y saldo medio del
  4.º trimestre, datos que no tenemos. Si la categoría supera el umbral,
  se lista para declaración manual.
- Una posición sin valoración en EUR a 31/12 NO entra en el fichero: se
  lista en ``excluded`` para valoración y declaración manual.
- Un valor sin ISIN no puede declararse con clave de identificación 1: se
  excluye y se lista (la clave 2 exige "Z"+país emisor, dato que no
  tenemos de forma fiable).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.models import Tenant
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.tax_modelo720_service import Modelo720Service

# --- Layout oficial (spec AEAT, verificado campo a campo) -------------------

RECORD_LEN = 500
CODING = "iso-8859-1"
# Vocales acentuadas (mayúsculas, tras upper()) -> sin acento. Ñ y Ç se
# conservan: la spec las admite.
_SIN_ACENTOS = str.maketrans("ÁÀÂÄÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜ", "AAAAAEEEEIIIIOOOOOUUUU")


def _text(value: str, length: int, align_right: bool = False, zero_pad: bool = False) -> str:
    """Campo alfanumérico: mayúsculas, sin caracteres de control, ancho fijo.

    La spec exige mayúsculas sin vocales acentuadas ni caracteres especiales
    (ISO-8859-1); los caracteres de control se sustituyen por espacio ANTES
    de recortar para no desplazar columnas.
    """
    # Primero mayúsculas y vocales sin acento, DESPUÉS el filtro: antes se
    # filtraba primero y "Muñoz Pérez José" salía "MU OZ P REZ JOS" (la ñ y
    # las vocales acentuadas en minúscula no son ASCII imprimible).
    clean = str(value).upper().translate(_SIN_ACENTOS)
    clean = "".join(
        ch if " " <= ch <= "~" or ch in "ÑÇ" else " "
        for ch in clean
    )
    clean = clean[:length]
    if align_right:
        return clean.rjust(length, "0" if zero_pad else " ")
    return clean.ljust(length)


def _num(value: Decimal | int | str, int_len: int, dec_len: int) -> str:
    """Campo numérico: parte entera + decimal, sin coma, ceros a la izquierda.

    Redondeo ROUND_HALF_UP ANTES de separar parte entera y decimal. Si el
    redondeo desborda la parte entera se falla en voz alta: rellenar
    silenciosamente desplazaría todos los bytes siguientes del registro.
    """
    dec = Decimal(str(value)).copy_abs().quantize(
        Decimal(1).scaleb(-dec_len), rounding=ROUND_HALF_UP
    )
    int_digits = str(int(dec))
    if len(int_digits) > int_len:
        raise ValueError(
            f"Modelo 720: importe {dec} excede el campo de {int_len} dígitos enteros"
        )
    frac = int((dec - int(dec)) * (10 ** dec_len))
    return int_digits.zfill(int_len) + str(frac).zfill(dec_len)


def _money_field(value: Decimal, sign_pos: bool = True) -> tuple[str, str]:
    """Signo + importe de 14 posiciones (12 enteras + 2 decimales).

    El signo sale del importe YA redondeado a céntimos: un -0,004 se escribe
    como 0,00 y no como "N" + ceros (un cero negativo que el impreso no admite).
    """
    digits = _num(value, 12, 2)
    sign = "N" if value < 0 and int(digits) else " "
    return sign, digits


class Modelo720FileService:
    """Genera el fichero de 500 bytes/registro del Modelo 720."""

    def generate(self, db: Session, fiscal_year: int) -> dict:
        """Genera el fichero o explica por qué no puede (available=false).

        Los datos identificativos del declarante son datos fiscales
        PERSONALES y se leen de la metadata del tenant del portfolio activo
        (nunca de query params ni de configuración global), bajo la clave
        ``tax_declarant``::

            {
              "nif": "12345678A",                 # obligatorio
              "apellidos_nombre": "APELLIDOS, NOMBRE",  # obligatorio
              "numero_declaracion": "7202025000001",    # obligatorio: 13 dígitos, empieza por 720
              "custody": {"US0378331005": "IE", "cash:USD": "IE"},  # obligatorio: custodia POR PARTIDA
              "custody_entities": {"US0378331005": {   # obligatorio POR PARTIDA (misma clave que custody)
                "name": "BROKER FICTICIO SA",
                "nif": "FICTICIO123",                  # NIF de la entidad en su país
                "street": "CALLE FICTICIA 1",          # domicilio ESTRUCTURADO (subcampos)
                "city": "DUBLIN", "zip": "D01", "country": "IE",
                "complement": "", "region": ""
              }},
              "filed_720_before": false,               # obligatorio: ¿presentó 720 en ejercicios anteriores?
              "first_acquisition_dates": {"US0378331005": "20230115"},  # obligatorio por ISIN
              "telefono": "600000000",
              "previous_year_isins": [],               # informativo (bajas a manual_review)
              "declaracion_anterior": "7202024000001",
              "complementaria": false,
              "sustitutiva": false
            }

        Solo genera fichero para categorías con ``exceeds`` True (tri-estado:
        "desconocido" NO genera; el chequeo de umbrales explica qué falta).
        """
        thresholds = Modelo720Service().check_thresholds(db, fiscal_year)
        portfolio = PortfolioFXService().portfolio(db)
        tenant = (
            db.get(Tenant, portfolio.tenant_id)
            if portfolio is not None and portfolio.tenant_id is not None
            else None
        )
        declarant = (tenant.metadata_ or {}).get("tax_declarant") if tenant else None
        if not isinstance(declarant, dict) or not declarant.get("nif") or not declarant.get("apellidos_nombre"):
            return {
                "available": False,
                "reason": (
                    "Faltan datos identificativos del declarante: el registro "
                    "de tipo 1 exige NIF y apellidos y nombre, y no se "
                    "inventan. Guárdalos en la metadata del tenant bajo la "
                    "clave 'tax_declarant' (nif, apellidos_nombre, "
                    "numero_declaracion, custody_country, "
                    "first_acquisition_dates...)."
                ),
                "thresholds": thresholds,
            }
        nif = str(declarant["nif"])
        apellidos_nombre = str(declarant["apellidos_nombre"])
        telefono = declarant.get("telefono")
        contacto = declarant.get("contacto")
        complementaria = bool(declarant.get("complementaria"))
        sustitutiva = bool(declarant.get("sustitutiva"))
        declaracion_anterior = declarant.get("declaracion_anterior")
        previous_year_isins = declarant.get("previous_year_isins") or []
        first_dates = {
            str(k).upper(): str(v).replace("-", "")
            for k, v in (declarant.get("first_acquisition_dates") or {}).items()
        }
        previous_isins = {str(i).upper() for i in previous_year_isins}

        # Número de declaración: la spec exige 13 dígitos que comiencen
        # por 720; rellenarlo con ceros sería un dato materialmente falso.
        numero_declaracion = str(declarant.get("numero_declaracion") or "")
        if not (
            len(numero_declaracion) == 13
            and numero_declaracion.isdigit()
            and numero_declaracion.startswith("720")
        ):
            return {
                "available": False,
                "reason": (
                    "Falta 'numero_declaracion' válido en tax_declarant: la "
                    "spec exige 13 dígitos que comiencen por 720 (número "
                    "secuencial de la declaración). No se genera un fichero "
                    "con ese campo inventado."
                ),
                "thresholds": thresholds,
            }
        # Custodia POR PARTIDA (129-130): el país es donde cada valor está
        # depositado/gestionado, nunca el prefijo del ISIN ni un país único
        # para toda la cartera (carteras mixtas). Mismo mapa que el chequeo.
        raw_custody = declarant.get("custody")
        custody_map = {
            str(k).upper(): str(v).strip().upper()
            for k, v in (raw_custody.items() if isinstance(raw_custody, dict) else [])
            if isinstance(v, str) and len(str(v).strip()) == 2
        }
        if not custody_map:
            return {
                "available": False,
                "reason": (
                    "Falta 'custody' en tax_declarant: mapa por partida "
                    "(ISIN/ticker → país ISO2 de depósito/gestión, "
                    "'cash:<DIVISA>' para cuentas). El país no se infiere del "
                    "ISIN ni se declara uno único para toda la cartera."
                ),
                "thresholds": thresholds,
            }
        # Entidad depositaria REAL y ESTRUCTURADA POR PARTIDA (190-230,
        # 231-250, 251-414): la spec no los deja en blanco para clave V y el
        # domicilio va por subcampos (251-302 vía, 303-342 complemento,
        # 343-372 ciudad, 373-402 región, 403-412 ZIP, 413-414 país). La
        # clave es el MISMO espacio que 'custody' (ISIN/ticker): dos
        # depositarios distintos en un mismo país no pueden recibir una
        # entidad común por ambigüedad.
        raw_entities = declarant.get("custody_entities")
        custody_entities: dict[str, dict] = {}
        if isinstance(raw_entities, dict):
            for k, v in raw_entities.items():
                if isinstance(v, dict):
                    custody_entities[str(k).strip().upper()] = v
        for partida, country in custody_map.items():
            ent = custody_entities.get(partida)
            if not ent or not all(
                ent.get(f) for f in ("name", "nif", "street", "city", "zip", "country")
            ):
                return {
                    "available": False,
                    "reason": (
                        f"Falta 'custody_entities' para '{partida}' en "
                        "tax_declarant (name, nif, street, city, zip, country "
                        "de la entidad depositaria REAL de ESA partida): la "
                        "entidad se liga a cada ISIN/cuenta, no se agrupa por "
                        "país."
                    ),
                    "thresholds": thresholds,
                }
            # Coherencia: el país del domicilio de la entidad debe ser el
            # país de custodia declarado para su partida (ni ES en un
            # custodio IE ni al revés).
            if str(ent.get("country") or "").strip().upper() != country:
                return {
                    "available": False,
                    "reason": (
                        f"Incoherencia en '{partida}': la entidad declara "
                        f"país de domicilio '{ent.get('country')}' pero la "
                        f"custodia de la partida es '{country}'. Corrige "
                        "custody / custody_entities."
                    ),
                    "thresholds": thresholds,
                }

        # Historial de presentación: la AUSENCIA de previous_year_isins no
        # confirma primera declaración. Sin filed_720_before explícito no se
        # puede asignar origen A/M: fail-closed.
        filed_before = declarant.get("filed_720_before")
        if type(filed_before) is not bool:
            # Solo booleano JSON real: "false", 0 o {} no valen — pasarían
            # por primera declaración y emitirían un origen A falso.
            return {
                "available": False,
                "reason": (
                    "Falta 'filed_720_before' (booleano true/false) en "
                    "tax_declarant: sin historial de presentación no se puede "
                    "asignar el origen (A primera declaración / M "
                    "modificación) sin inventarlo."
                ),
                "thresholds": thresholds,
            }
        if filed_before is True:
            return {
                "available": False,
                "reason": (
                    "Ya se presentó el 720 en ejercicios anteriores: el origen "
                    "(A/M) exige los importes de la última declaración para "
                    "evaluar el incremento conjunto >20.000 € por categoría, "
                    "dato que no tenemos. Declarar manualmente o aportar esos "
                    "importes."
                ),
                "thresholds": thresholds,
            }
        if previous_isins:
            return {
                "available": False,
                "reason": (
                    "Contradicción: filed_720_before=false pero hay "
                    "previous_year_isins declarados. Reconcilia el historial "
                    "en tax_declarant antes de generar."
                ),
                "thresholds": thresholds,
            }

        detail_records: list[str] = []
        manual_review: list[dict] = []
        excluded: list[dict] = (
            list(thresholds.get("unvalued") or [])
            + list(thresholds.get("foreign_unverified") or [])
            + list(thresholds.get("short_positions") or [])
            + list(thresholds.get("stale_snapshots") or [])
        )
        sum_val1 = Decimal("0")
        sum_val2 = Decimal("0")

        valores = thresholds["categories"]["valores"]
        if valores["exceeds"] is True:
            # Fecha de incorporación: campo numérico EXIGIDO (415-422).
            # Sin fecha real por ISIN no se genera el fichero (un campo
            # en blanco invalida el registro y no se inventa).
            missing_dates = sorted({
                pos["ticker"]
                for pos in valores["positions"]
                if (pos.get("isin") or "").upper()
                and not first_dates.get((pos.get("isin") or "").upper())
            })
            if missing_dates:
                return {
                    "available": False,
                    "reason": (
                        "Falta la fecha de primera adquisición (obligatoria, "
                        "posiciones 415-422) para: " + ", ".join(missing_dates) +
                        ". Aporta tax_declarant.first_acquisition_dates "
                        "(ISIN → fecha YYYYMMDD)."
                    ),
                    "excluded": excluded,
                    "thresholds": thresholds,
                }
            # Un MISMO ISIN en dos carteras puede estar en dos custodios
            # distintos: la config por ISIN no puede representarlo y el
            # fichero asignaría la misma entidad a ambas filas. No
            # representable -> fail-closed.
            isin_counts: dict[str, int] = {}
            for pos in valores["positions"]:
                key = (pos.get("isin") or "").upper()
                if key:
                    isin_counts[key] = isin_counts.get(key, 0) + 1
            duplicated = sorted(k for k, n in isin_counts.items() if n > 1)
            if duplicated:
                return {
                    "available": False,
                    "reason": (
                        "Configuración no representable: el mismo ISIN aparece "
                        "en varias carteras (" + ", ".join(duplicated) + ") y "
                        "podría estar depositado en custodios distintos; la "
                        "declaración por ISIN no puede distinguirlos. Declarar "
                        "manualmente con la entidad correcta por cartera."
                    ),
                    "excluded": excluded,
                    "thresholds": thresholds,
                }
            for pos in valores["positions"]:
                isin = (pos.get("isin") or "").upper()
                if not isin:
                    excluded.append({
                        "ticker": pos["ticker"],
                        "reason": "Sin ISIN: la clave 2 (valores sin ISIN) exige 'Z'+país emisor, dato no disponible. Declarar manualmente.",
                    })
                    continue
                # Lotes: la norma exige un registro POR FECHA de adquisición.
                # Sin cantidades por lote no se puede partir el registro:
                # varias fechas -> no se genera (available=false).
                raw_dates = (declarant.get("first_acquisition_dates") or {}).get(isin)
                if isinstance(raw_dates, (list, tuple)):
                    distinct = {str(d).replace("-", "") for d in raw_dates}
                    if len(distinct) > 1:
                        return {
                            "available": False,
                            "reason": (
                                f"{pos['ticker']} ({isin}) tiene lotes con "
                                "fechas de adquisición distintas: la norma "
                                "exige un registro por fecha y no tenemos las "
                                "cantidades por lote. Declarar manualmente."
                            ),
                            "excluded": excluded,
                            "thresholds": thresholds,
                        }
                value = Decimal(str(pos["value_base"]))
                first_date = first_dates[isin]
                if not (len(first_date) == 8 and first_date.isdigit()):
                    return {
                        "available": False,
                        "reason": (
                            f"La fecha de primera adquisición de {pos['ticker']} "
                            f"('{first_date}') no es YYYYMMDD: corrígela en "
                            "tax_declarant.first_acquisition_dates."
                        ),
                        "excluded": excluded,
                        "thresholds": thresholds,
                    }
                custody = custody_map.get(isin)
                if custody is None:
                    excluded.append({
                        "ticker": pos["ticker"],
                        "reason": "Sin país de custodia declarado para este ISIN en tax_declarant.custody: el campo 129-130 no se infiere. Declarar manualmente.",
                    })
                    continue
                if custody == "ES":
                    excluded.append({
                        "ticker": pos["ticker"],
                        "reason": "Custodia declarada en España: no es bien en el extranjero, no va en el 720.",
                    })
                    continue
                # previous_year_isins ya no puede coexistir con
                # filed_720_before=false (gate anterior): origen "A"
                # legítimo de primera declaración.
                ent = custody_entities[isin]
                detail_records.append(
                    self._detail_valores(
                        fiscal_year, nif, apellidos_nombre, pos, isin,
                        value, "A", first_date, custody, ent,
                    )
                )
                sum_val1 += value
            # Bajas: sin fecha EFECTIVA de extinción no se genera registro
            # (inventar 31/12 sería un dato falso); se listan para que el
            # declarante las presente manualmente con su fecha real.
            held = {
                (p.get("isin") or "").upper()
                for p in valores["positions"]
            }
            held.discard("")
            for isin in sorted(previous_isins - held):
                manual_review.append({
                    "ticker": isin,
                    "isin": isin,
                    "reason": (
                        "ISIN declarado el año anterior y ya no poseído: posible "
                        "BAJA. Requiere la fecha efectiva de extinción; declarar "
                        "manualmente."
                    ),
                })

        cuentas = thresholds["categories"]["cuentas"]
        if cuentas["exceeds"] is True:
            # Clave C NO se genera: exige identificador de cuenta asignado
            # por la entidad, identidad real de la entidad y saldo medio del
            # 4.º trimestre — datos que no tenemos y no se inventan.
            manual_review.append({
                "ticker": "cuentas",
                "reason": (
                    "La categoría CUENTAS supera el umbral, pero el registro C "
                    "exige identificador de cuenta, identidad de la entidad y "
                    "saldo medio del 4.º trimestre: no se genera fichero para "
                    "cuentas. Declarar manualmente."
                ),
            })

        if not detail_records:
            return {
                "available": False,
                "reason": (
                    "Ninguna categoría generable supera los 50.000 € o todos "
                    "los registros quedaron excluidos por datos incompletos. "
                    "Sin fichero generado (revisa 'excluded' y 'manual_review')."
                ),
                "excluded": excluded,
                "manual_review": manual_review,
                "thresholds": thresholds,
            }

        summary = self._summary_record(
            fiscal_year, nif, apellidos_nombre,
            telefono=telefono, contacto=contacto,
            numero_declaracion=numero_declaracion,
            complementaria=complementaria, sustitutiva=sustitutiva,
            declaracion_anterior=declaracion_anterior,
            detail_count=len(detail_records),
            sum_val1=sum_val1, sum_val2=sum_val2,
        )
        content = "\n".join([summary, *detail_records]) + "\n"
        return {
            "available": True,
            "encoding": CODING,
            "record_length": RECORD_LEN,
            "detail_records": len(detail_records),
            "content": content,
            "excluded": excluded,
            "manual_review": manual_review,
            "thresholds": thresholds,
            "notas": [
                "Fichero conforme al diseño de registro oficial AEAT "
                "(500 bytes, ISO-8859-1): AYUDA DE CÓMPUTO — revisar antes "
                "de presentar por TGVI Online.",
                "Origen siempre 'A': si la categoría ya se declaró y el "
                "incremento conjunto supera 20.000 € corresponde 'M' "
                "(ver 'manual_review').",
                "Un ISIN comprado en lotes con fechas distintas exige un "
                "registro por lote: aquí se genera uno con la fecha "
                "aportada; si hubo varias fechas, revisar manualmente.",
                "Cuentas (clave C) y bajas no se generan: requieren datos "
                "que no tenemos (ver 'manual_review').",
            ],
        }

    # --- Registros -----------------------------------------------------------

    def _summary_record(
        self, fiscal_year, nif, apellidos_nombre, *, telefono, contacto,
        numero_declaracion, complementaria, sustitutiva,
        declaracion_anterior, detail_count, sum_val1, sum_val2,
    ) -> str:
        r = "1"                                    # 1: tipo de registro
        r += "720"                                 # 2-4: modelo
        r += str(fiscal_year)                      # 5-8: ejercicio
        r += _text(nif, 9, align_right=True, zero_pad=True)   # 9-17: NIF
        r += _text(apellidos_nombre, 40)           # 18-57: apellidos y nombre
        r += "T"                                   # 58: tipo de soporte
        r += _text(telefono or "", 9, align_right=True, zero_pad=True)  # 59-67
        r += _text(contacto or apellidos_nombre, 40)  # 68-107: con quien relacionarse
        r += _text(numero_declaracion or "", 13, align_right=True, zero_pad=True)  # 108-120
        r += "C" if complementaria else " "        # 121: complementaria
        r += "S" if sustitutiva else " "           # 122: sustitutiva
        r += _text(declaracion_anterior or "", 13, align_right=True, zero_pad=True)  # 123-135
        r += str(detail_count).zfill(9)            # 136-144: total registros
        s1, v1 = _money_field(sum_val1)            # 145 signo
        r += s1 + _num(sum_val1, 15, 2)            # 146-162: suma valoración 1
        s2, v2 = _money_field(sum_val2)
        r += s2 + _num(sum_val2, 15, 2)            # 163-180: suma valoración 2
        r += " " * 320                             # 181-500: blancos
        assert len(r) == RECORD_LEN, f"tipo 1: {len(r)} bytes"
        return r

    def _detail_head(self, fiscal_year, nif, apellidos_nombre, clave_bien, subclave, pais) -> str:
        r = "2"                                    # 1: tipo de registro
        r += "720"                                 # 2-4: modelo
        r += str(fiscal_year)                      # 5-8: ejercicio
        r += _text(nif, 9, align_right=True, zero_pad=True)   # 9-17: NIF declarante
        r += _text(nif, 9, align_right=True, zero_pad=True)   # 18-26: NIF declarado
        r += " " * 9                               # 27-35: NIF representante
        r += _text(apellidos_nombre, 40)           # 36-75: nombre declarado
        r += "1"                                   # 76: condición = titular
        r += " " * 25                              # 77-101: tipo titularidad
        r += clave_bien                            # 102: clave tipo de bien
        r += subclave                              # 103: subclave
        r += " " * 25                              # 104-128: derecho real inmueble
        r += _text(pais, 2)                        # 129-130: código de país
        return r

    def _detail_tail(
        self, fecha_incorporacion, origen, fecha_extincion,
        val1, val2, representacion, cantidad,
    ) -> str:
        r = _text(fecha_incorporacion, 8)          # 415-422: fecha incorporación
        r += origen                                # 423: origen A/M/C
        r += _text(fecha_extincion, 8)             # 424-431: fecha extinción
        r += ("N" if val1 < 0 else " ")            # 432: signo valoración 1
        r += _num(val1, 12, 2)                     # 433-446: valoración 1
        r += ("N" if val2 < 0 else " ")            # 447: signo valoración 2
        r += _num(val2, 12, 2)                     # 448-461: valoración 2
        r += representacion                        # 462: representación (V/I)
        r += _num(cantidad, 10, 2)                 # 463-474: número de valores
        r += " "                                   # 475: clave inmueble (B)
        r += _num(100, 3, 2)                       # 476-480: % participación
        r += " " * 20                              # 481-500: blancos
        return r

    def _detail_valores(
        self, fiscal_year, nif, apellidos_nombre, pos, isin,
        value, origin, first_date, custody_country, entity,
    ) -> str:
        # 129-130: país donde los valores están DEPOSITADOS O GESTIONADOS
        # (spec, pág. 23): dato declarado por partida, nunca el prefijo del ISIN.
        r = self._detail_head(fiscal_year, nif, apellidos_nombre, "V", "1", custody_country)
        r += "1"                                   # 131: identificación por ISIN
        r += _text(isin, 12)                       # 132-143: ISIN
        r += " "                                   # 144: clave ID cuenta (no C)
        r += " " * 11                              # 145-155: BIC
        r += " " * 34                              # 156-189: código cuenta
        # 190-414: entidad depositaria REAL con domicilio ESTRUCTURADO por
        # subcampos (spec, pág. 26): la entidad es la del país de custodia
        # de ESTA partida, no una global replicada.
        r += _text(entity["name"], 41)             # 190-230: entidad
        r += _text(entity["nif"], 20)              # 231-250: NIF de la entidad en su país
        r += _text(entity["street"], 52)           # 251-302: tipo/nombre vía y número
        r += _text(entity.get("complement") or "", 40)  # 303-342: complemento
        r += _text(entity["city"], 30)             # 343-372: ciudad
        r += _text(entity.get("region") or "", 30) # 373-402: región/provincia
        r += _text(entity["zip"], 10)              # 403-412: código postal
        r += _text(entity["country"], 2)           # 413-414: país de la entidad
        r += self._detail_tail(
            first_date, origin, "",
            value, Decimal("0"), "A",
            # nosemgrep: gerarai-money-none-to-zero -- quantity de una posicion persistida (NOT NULL); el fichero 720 exige un numero
            Decimal(str(pos.get("quantity") or 0)),
        )
        assert len(r) == RECORD_LEN, f"detalle V: {len(r)} bytes"
        return r
