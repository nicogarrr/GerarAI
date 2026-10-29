"""Reviewed ticker -> CNMV issuer mapping (Spanish listed equities).

Parent constraint: no company-name-to-NIF guessing. Entries are reviewed
manually against CNMV registry pages (normalized legal name + NIF + ISIN +
ticker aliases). Unknown, ambiguous or conflicting mappings resolve to None
(unavailable) — attribution is never guessed.

Reviewed 2026-09-22 against CNMV entity/ISIN information pages.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CNMVIssuer:
    ticker: str
    legal_name: str          # normalized CNMV legal name (uppercase)
    nif: str
    isin: str
    aliases: tuple[str, ...] = ()


# Reviewed seed table (IBEX heavyweights). Extend only after verifying each
# entry against the CNMV registry; never auto-generate rows.
# Aliases ending in "SA"/"SOCIEDAD ANONIMA" are the ESEF legal-name forms,
# verified 2026-09-24 against filings.xbrl.org (each matched exactly one LEI).
REVIEWED_ISSUERS: tuple[CNMVIssuer, ...] = (
    CNMVIssuer("SAN", "BANCO SANTANDER, S.A.", "A-39000013", "ES0113900J37", ("SANTANDER", "SAN.MC")),
    CNMVIssuer("ITX", "INDUSTRIA DE DISEÑO TEXTIL, S.A.", "A-15075062", "ES0148396007", ("INDITEX", "ITX.MC")),
    CNMVIssuer("IBE", "IBERDROLA, S.A.", "A-48010611", "ES0144580Y14", ("IBERDROLA", "IBE.MC", "IBERDROLA SA")),
    CNMVIssuer("BBVA", "BANCO BILBAO VIZCAYA ARGENTARIA, S.A.", "A-48265169", "ES0113211835", ("BBVA", "BBVA.MC", "BANCO BILBAO VIZCAYA ARGENTARIA SOCIEDAD ANONIMA")),
    CNMVIssuer("TEF", "TELEFONICA, S.A.", "A-28015865", "ES0178430E18", ("TELEFONICA", "TEF.MC", "TELEFONICA SA")),
    CNMVIssuer("REP", "REPSOL, S.A.", "A-78374725", "ES0173516115", ("REPSOL", "REP.MC", "REPSOL SA")),
    # Tanda 1 (2026-09-25): verificada fila a fila contra paginas oficiales
    # CNMV - datosentidad (nombre legal + NIF) y ancv/isin (ISIN de acciones
    # CFI ESVU** y nemotecnico oficial del FISN). FERROVIAL se excluye a
    # proposito: la cotizada actual es FERROVIAL N.V. (entidad neerlandesa,
    # N0119863I) y el ESEF del manifest corresponde a la S.A. extinguida -
    # conflicto de entidad, se deja sin resolver.
    CNMVIssuer("TRE", "TECNICAS REUNIDAS, S.A.", "A-28092583", "ES0178165017", ("TECNICAS REUNIDAS", "TRE.MC", "TECNICAS REUNIDAS SA")),
    CNMVIssuer("CLNX", "CELLNEX TELECOM, S.A.", "A-64907306", "ES0105066007", ("CELLNEX", "CLNX.MC", "CELLNEX TELECOM SA")),
    CNMVIssuer("ELE", "ENDESA, S.A.", "A-28023430", "ES0130670112", ("ENDESA", "ELE.MC", "ENDESA SA")),
    CNMVIssuer("CABK", "CAIXABANK, S.A.", "A-08663619", "ES0140609019", ("CAIXABANK", "CABK.MC", "CAIXABANK SA")),
    CNMVIssuer("ENG", "ENAGAS, S.A.", "A-28294726", "ES0130960018", ("ENAGAS", "ENG.MC", "ENAGAS SA")),
    CNMVIssuer("ACS", "ACS, ACTIVIDADES DE CONSTRUCCION Y SERVICIOS, S.A.", "A-28004885", "ES0167050915", ("ACS", "ACS.MC", "ACS ACTIVIDADES DE CONSTRUCCION Y SERVICIOS SA")),
    CNMVIssuer("MAP", "MAPFRE, S.A.", "A-08055741", "ES0124244E34", ("MAPFRE", "MAP.MC", "MAPFRE SA")),
    CNMVIssuer("AMS", "AMADEUS IT GROUP, S.A.", "A-84236934", "ES0109067019", ("AMADEUS", "AMS.MC", "AMADEUS IT GROUP SOCIEDAD ANONIMA", "AMADEUS IT GROUP SA")),
    CNMVIssuer("ANA", "ACCIONA, S.A.", "A-08001851", "ES0125220311", ("ACCIONA", "ANA.MC", "ACCIONA SA")),
    CNMVIssuer("ANE", "CORPORACION ACCIONA ENERGIAS RENOVABLES, S.A.", "A-85483311", "ES0105563003", ("ACCIONA ENERGIA", "ANE.MC", "CORPORACION ACCIONA ENERGIAS RENOVABLES SA")),
    CNMVIssuer("PSG", "PROSEGUR, COMPAÑIA DE SEGURIDAD, S.A.", "A-28430882", "ES0175438003", ("PROSEGUR", "PSG.MC", "PROSEGUR COMPAÑIA DE SEGURIDAD SA")),
    CNMVIssuer("IDR", "INDRA SISTEMAS, S.A.", "A-28599033", "ES0118594417", ("INDRA", "IDR.MC", "INDRA SISTEMAS SA")),
    CNMVIssuer("VIS", "VISCOFAN, S.A.", "A-31065501", "ES0184262212", ("VISCOFAN", "VIS.MC", "VISCOFAN SA")),
    CNMVIssuer("AENA", "AENA, S.M.E., S.A.", "A-86212420", "ES0105046017", ("AENA", "AENA.MC", "AENA SME SA", "AENA S.M.E. SA")),
    CNMVIssuer("BKT", "BANKINTER, S.A.", "A-28157360", "ES0113679I37", ("BANKINTER", "BKT.MC", "BANKINTER SOCIEDAD ANONIMA", "BANKINTER SA")),
    CNMVIssuer("SAB", "BANCO DE SABADELL, S.A.", "A-08000143", "ES0113860A34", ("SABADELL", "SAB.MC", "BANCO SABADELL", "BANCO DE SABADELL SA")),
    CNMVIssuer("NTGY", "NATURGY ENERGY GROUP, S.A.", "A-08015497", "ES0116870314", ("NATURGY", "NTGY.MC", "NATURGY ENERGY GROUP SA")),
    CNMVIssuer("MRL", "MERLIN PROPERTIES, SOCIMI, S.A.", "A-86977790", "ES0105025003", ("MERLIN", "MRL.MC", "MERLIN PROPERTIES SOCIMI SA")),
    # GRF usa la clase A con voto (ES0171996087); la clase B sin voto
    # (ES0171996095) queda como alias, no como ISIN principal.
    CNMVIssuer("GRF", "GRIFOLS, S.A.", "A-58389123", "ES0171996087", ("GRIFOLS", "GRF.MC", "GRIFOLS SA")),
    # Tanda 2 (2026-09-25): mismo metodo que la tanda 1 (datosentidad +
    # ancv/isin de CNMV). Cuando el FISN no da nemotecnico corto, el ticker
    # se confirma con ficha BME/bsmarkets (LDA, LRE). MEDIASET ESPAÑA se
    # excluye: sin ISIN equity en CNMV tras su absorcion por MFE - hueco
    # honesto, como FERROVIAL.
    CNMVIssuer("FCC", "FOMENTO DE CONSTRUCCIONES Y CONTRATAS, S.A.", "A-28037224", "ES0122060314", ("FCC", "FCC.MC", "FOMENTO DE CONSTRUCCIONES Y CONTRATAS SA")),
    CNMVIssuer("COL", "COLONIAL SFL, SOCIMI, S.A.", "A-28027399", "ES0139140174", ("COLONIAL", "COL.MC", "INMOBILIARIA COLONIAL SOCIMI SA", "INMOBILIARIA COLONIAL SOCIMI SOCIEDAD ANONIMA")),
    CNMVIssuer("A3M", "ATRESMEDIA CORPORACION DE MEDIOS DE COMUNICACION, S.A.", "A-78839271", "ES0109427734", ("ATRESMEDIA", "A3M.MC", "ATRESMEDIA CORPORACION DE MEDIOS DE COMUNICACION SA")),
    CNMVIssuer("LOG", "LOGISTA INTEGRAL, S.A.", "A-87008579", "ES0105027009", ("LOGISTA", "LOG.MC", "LOGISTA INTEGRAL SA")),
    CNMVIssuer("VID", "VIDRALA, S.A.", "A-01004324", "ES0183746314", ("VIDRALA", "VID.MC", "VIDRALA SA")),
    CNMVIssuer("CIE", "CIE AUTOMOTIVE, S.A.", "A-20014452", "ES0105630315", ("CIE", "CIE.MC", "CIE AUTOMOTIVE SA")),
    CNMVIssuer("ACX", "ACERINOX, S.A.", "A-28250777", "ES0132105018", ("ACERINOX", "ACX.MC", "ACERINOX SA")),
    CNMVIssuer("FDR", "FLUIDRA, S.A.", "A-17728593", "ES0137650018", ("FLUIDRA", "FDR.MC", "FLUIDRA SA")),
    CNMVIssuer("ALM", "ALMIRALL, S.A.", "A-58869389", "ES0157097017", ("ALMIRALL", "ALM.MC", "ALMIRALL SA")),
    CNMVIssuer("ENC", "ENCE ENERGIA Y CELULOSA, S.A.", "A-28212264", "ES0130625512", ("ENCE", "ENC.MC", "ENCE ENERGIA Y CELULOSA SA")),
    CNMVIssuer("TLGO", "TALGO, S.A.", "A-84453075", "ES0105065009", ("TALGO", "TLGO.MC", "TALGO SA")),
    CNMVIssuer("ROVI", "LABORATORIOS FARMACEUTICOS ROVI, S.A.", "A-28041283", "ES0157261019", ("ROVI", "ROVI.MC", "LABORATORIOS FARMACEUTICOS ROVI SA")),
    CNMVIssuer("OLE", "DEOLEO, S.A.", "A-48012009", "ES0110047919", ("DEOLEO", "OLE.MC", "DEOLEO SA")),
    CNMVIssuer("CAF", "CONSTRUCCIONES Y AUXILIAR DE FERROCARRILES, S.A.", "A-20001020", "ES0121975009", ("CAF", "CAF.MC", "CONSTRUCCIONES Y AUXILIAR DE FERROCARRILES SA")),
    CNMVIssuer("OHL", "OBRASCON HUARTE LAIN, S.A.", "A-48010573", "ES0142090317", ("OHLA", "OHL.MC", "OBRASCON HUARTE LAIN SA")),
    CNMVIssuer("GEST", "GESTAMP AUTOMOCION, S.A.", "A-48943864", "ES0105223004", ("GESTAMP", "GEST.MC", "GESTAMP AUTOMOCION SA")),
    CNMVIssuer("ENO", "ELECNOR, S.A.", "A-48027056", "ES0129743318", ("ELECNOR", "ENO.MC", "ELECNOR SA")),
    CNMVIssuer("GCO", "GRUPO CATALANA OCCIDENTE, S.A.", "A-08168064", "ES0116920333", ("CATALANA OCCIDENTE", "GCO.MC", "GRUPO CATALANA OCCIDENTE SA")),
    CNMVIssuer("LDA", "LINEA DIRECTA ASEGURADORA, S.A., COMPAÑIA DE SEGUROS Y REASEGUROS", "A-80871031", "ES0105546008", ("LINEA DIRECTA", "LDA.MC", "LINEA DIRECTA ASEGURADORA SOCIEDAD ANONIMA COMPAÑIA DE SEGUROS Y REASEGUROS")),
    CNMVIssuer("CASH", "PROSEGUR CASH, S.A.", "A-87498564", "ES0105229001", ("PROSEGUR CASH", "CASH.MC", "PROSEGUR CASH SA")),
    CNMVIssuer("LRE", "LAR ESPAÑA REAL ESTATE SOCIMI, S.A.", "A-86918307", "ES0105015012", ("LAR ESPAÑA", "LRE.MC", "LAR ESPAÑA REAL ESTATE SOCIMI SA")),
    CNMVIssuer("TUB", "TUBACEX, S.A.", "A-01003946", "ES0132945017", ("TUBACEX", "TUB.MC", "TUBACEX SA")),
    CNMVIssuer("ALNT", "ALANTRA PARTNERS, S.A.", "A-81862724", "ES0126501131", ("ALANTRA", "ALNT.MC", "ALANTRA PARTNERS SA")),
    CNMVIssuer("AZK", "AZKOYEN, S.A.", "A-31065618", "ES0112458312", ("AZKOYEN", "AZK.MC", "AZKOYEN SA")),
    # Tanda 3 (2026-09-25): mismo metodo CNMV. RED confirmado con Yahoo
    # (RED.MC) porque el FISN no da codigo corto. EDREAMS ODIGEO excluida:
    # sin ISIN equity en CNMV (A02850956) - hueco honesto documentado.
    CNMVIssuer("RED", "REDEIA CORPORACION, S.A.", "A-78003662", "ES0173093024", ("REDEIA", "RED.MC", "RED ELECTRICA", "REDEIA CORPORACION SA")),
    CNMVIssuer("HOME", "NEINOR HOMES, S.A.", "A-95786562", "ES0105251005", ("NEINOR", "HOME.MC", "NEINOR HOMES SA")),
    CNMVIssuer("FAE", "FAES FARMA, S.A.", "A-48004360", "ES0134950F36", ("FAES", "FAE.MC", "FAES FARMA SA")),
    CNMVIssuer("MEL", "MELIA HOTELS INTERNATIONAL S.A.", "A-78304516", "ES0176252718", ("MELIA", "MEL.MC", "MELIA HOTELS", "MELIA HOTELS INTERNATIONAL SA")),
    CNMVIssuer("EBRO", "EBRO FOODS, S.A.", "A-47412333", "ES0112501012", ("EBRO", "EBRO.MC", "EBRO FOODS SA")),
    CNMVIssuer("SCYR", "SACYR, S.A.", "A-28013811", "ES0182870214", ("SACYR", "SCYR.MC", "SACYR SA")),
    CNMVIssuer("SLR", "SOLARIA ENERGIA Y MEDIOAMBIENTE, S.A.", "A-83511501", "ES0165386014", ("SOLARIA", "SLR.MC", "SOLARIA ENERGIA Y MEDIO AMBIENTE SA")),
    CNMVIssuer("ECR", "ERCROS, S.A.", "A-08000630", "ES0125140A14", ("ERCROS", "ECR.MC", "ERCROS SA")),
    CNMVIssuer("IBG", "IBERPAPEL GESTION, S.A.", "A-21248893", "ES0147561015", ("IBERPAPEL", "IBG.MC", "IBERPAPEL GESTION SA")),
    # Tandas 4-5 (2026-09-25): mismo metodo CNMV. MINERSA excluida: sin
    # nemotecnico corto confirmable en fuente oficial. Clases sin voto
    # (RIO ACNV, URBAS ACNV, GRF B) nunca como ISIN principal.
    CNMVIssuer("APPS", "APPLUS SERVICES, S.A.", "A-64622970", "ES0105022000", ("APPLUS", "APPS.MC", "APPLUS SERVICES SA")),
    CNMVIssuer("TRG", "TUBOS REUNIDOS, S.A.", "A-48011555", "ES0180850416", ("TUBOS REUNIDOS", "TRG.MC", "TUBOS REUNIDOS SA")),
    CNMVIssuer("MCM", "MIQUEL Y COSTAS & MIQUEL, S.A.", "A-08020729", "ES0164180012", ("MIQUEL Y COSTAS", "MCM.MC", "MIQUEL Y COSTAS & MIQUEL SA")),
    CNMVIssuer("PRM", "PRIM, S.A.", "A-28165587", "ES0170884417", ("PRIM", "PRM.MC", "PRIM SA")),
    CNMVIssuer("RLIA", "REALIA BUSINESS, S.A.", "A-81787889", "ES0173908015", ("REALIA", "RLIA.MC", "REALIA BUSINESS SA")),
    CNMVIssuer("RIO", "BODEGAS RIOJANAS, S.A.", "A-26000398", "ES0115002018", ("BODEGAS RIOJANAS", "RIO.MC", "BODEGAS RIOJANAS SOCIEDAD ANONIMA", "BODEGAS RIOJANAS SA")),
    CNMVIssuer("LGT", "LINGOTES ESPECIALES, S.A.", "A-47007109", "ES0158480311", ("LINGOTES", "LGT.MC", "LINGOTES ESPECIALES SA")),
    CNMVIssuer("UBS", "URBAS GRUPO FINANCIERO, S.A.", "A-08049793", "ES0182280018", ("URBAS", "UBS.MC", "URBAS GRUPO FINANCIERO SA")),
    CNMVIssuer("EZE", "GRUPO EZENTIS, S.A.", "A-28085207", "ES0172708234", ("EZENTIS", "EZE.MC", "GRUPO EZENTIS SA")),
    CNMVIssuer("AMP", "AMPER, S.A.", "A-28079226", "ES0109260291", ("AMPER", "AMP.MC", "AMPER SA")),
    CNMVIssuer("CBAV", "CLINICA BAVIERA, S.A.", "A-80240427", "ES0119037010", ("CLINICA BAVIERA", "CBAV.MC", "CLINICA BAVIERA SA")),
    CNMVIssuer("NEA", "NICOLAS CORREA, S.A.", "A-28041317", "ES0166300212", ("NICOLAS CORREA", "NEA.MC", "NICOLAS CORREA SA")),
    CNMVIssuer("ENER", "ECOENER, S.A.", "A-70611538", "ES0105548004", ("ECOENER", "ENER.MC", "ECOENER SA")),
    CNMVIssuer("ATRY", "ATRYS HEALTH, S.A.", "A-84942150", "ES0105148003", ("ATRYS", "ATRY.MC", "ATRYS HEALTH SA")),
    CNMVIssuer("AEDAS", "AEDAS HOMES, S.A.", "A-87586483", "ES0105287009", ("AEDAS", "AEDAS.MC", "AEDAS HOMES SA")),
    CNMVIssuer("VOC", "VOCENTO, S.A.", "A-48001655", "ES0114820113", ("VOCENTO", "VOC.MC", "VOCENTO SA")),
    CNMVIssuer("ADZ", "ADOLFO DOMINGUEZ, S.A.", "A-32104226", "ES0106000013", ("ADOLFO DOMINGUEZ", "ADZ.MC", "ADOLFO DOMINGUEZ SA")),
    CNMVIssuer("MDF", "DURO FELGUERA, S.A.", "A-28004026", "ES0162600003", ("DURO FELGUERA", "MDF.MC", "DURO FELGUERA SA")),
    CNMVIssuer("GAM", "GENERAL DE ALQUILER DE MAQUINARIA, S.A.", "A-83443556", "ES0141571192", ("GAM", "GAM.MC", "GENERAL DE ALQUILER DE MAQUINARIA SA")),
    CNMVIssuer("SQRL", "SQUIRREL MEDIA, S.A.", "A-84856947", "ES0183304080", ("SQUIRREL", "SQRL.MC", "SQUIRREL MEDIA SA")),
    CNMVIssuer("MTB", "MONTEBALITO, S.A.", "A-28294700", "ES0116494016", ("MONTEBALITO", "MTB.MC", "MONTEBALITO SA")),
    CNMVIssuer("NYE", "NYESA VALORES CORPORACION, S.A.", "A-08074320", "ES0150480194", ("NYESA", "NYE.MC", "NYESA VALORES CORPORACION SA")),
    CNMVIssuer("PVA", "PESCANOVA, S.A.", "A-36603587", "ES0169350016", ("PESCANOVA", "PVA.MC", "PESCANOVA SA")),
    # Tanda 6 (2026-09-25): misma verificacion CNMV (ancv/isin + caption del
    # nombre legal; el NIF viene de la ficha oficial). PUIG usa la clase B
    # cotizada (ES0105777017); la clase A no cotiza. IAG NIF sin guion segun
    # el buscador oficial.
    CNMVIssuer("R4", "RENTA 4 BANCO, S.A.", "A-82473018", "ES0173358039", ("RENTA 4", "R4.MC", "RENTA 4 BANCO SA")),
    CNMVIssuer("AI", "AIRTIFICIAL INTELLIGENCE STRUCTURES, S.A.", "A-28249977", "ES0152768109", ("AIRTIFICIAL", "AI.MC", "AIRTIFICIAL INTELLIGENCE STRUCTURES SA")),
    CNMVIssuer("ALB", "CORPORACION FINANCIERA ALBA, S.A.", "A-28060903", "ES0117160111", ("CORPORACION FINANCIERA ALBA", "ALB.MC", "CORPORACION FINANCIERA ALBA SA")),
    CNMVIssuer("GSJ", "GRUPO EMPRESARIAL SAN JOSE, S.A.", "A-36046993", "ES0180918015", ("SAN JOSE", "GSJ.MC", "GRUPO EMPRESARIAL SAN JOSE SA")),
    CNMVIssuer("RJF", "LABORATORIO REIG JOFRE, S.A.", "A-96184882", "ES0165359029", ("REIG JOFRE", "RJF.MC", "LABORATORIO REIG JOFRE SA")),
    CNMVIssuer("IAG", "INTERNATIONAL CONSOLIDATED AIRLINES GROUP, S.A.", "A-85845535", "ES0177542018", ("IAG", "IAG.MC", "INTERNATIONAL CONSOLIDATED AIRLINES GROUP SA")),
    CNMVIssuer("UNI", "UNICAJA BANCO, S.A.", "A-93139053", "ES0180907000", ("UNICAJA", "UNI.MC", "UNICAJA BANCO SA")),
    CNMVIssuer("PUIG", "PUIG BRANDS, S.A.", "A-66674904", "ES0105777017", ("PUIG", "PUIG.MC", "PUIG BRANDS SA")),
    CNMVIssuer("DOM", "GLOBAL DOMINION ACCESS, S.A.", "A-95034856", "ES0105130001", ("GLOBAL DOMINION", "DOM.MC", "GLOBAL DOMINION ACCESS SA")),
    CNMVIssuer("CMO", "CEMENTOS MOLINS, S.A.", "A-08017535", "ES0117360117", ("CEMENTOS MOLINS", "CMO.MC", "CEMENTOS MOLINS SA")),
    CNMVIssuer("PHM", "PHARMA MAR, S.A.", "A-78267176", "ES0169501022", ("PHARMAMAR", "PHM.MC", "PHARMA MAR SA")),
    # Tanda 7 (2026-09-25): misma verificacion CNMV. Exclusiones de la tanda:
    # CLEOP y URBAR solo tienen clases ACNV (acciones sin voto) listadas en
    # BME; la clase ordinaria no cotiza. Quedan excluidas por criterio de
    # producto (2026-09-25): mejor hueco honesto que mapear una clase sin
    # voto que el usuario no puede comprar. MINERSA tiene ISIN (ES0163960018)
    # pero sin nemotecnico corto activo confirmable. OPDENERGY dejo de cotizar el 19-abr-2024 (opdenergy.com)
    # y MINOR HOTELS (ex-NH) quedo excluida de negociacion el 25-sep-2025
    # (opa de exclusion, Sociedades Rectoras) - exclusiones honestas aunque
    # sigan presentando ESEF. Tickers cortos no presentes en el FISN confirmados en
    # BME/Yahoo/Morningstar (documentado en el PR).
    CNMVIssuer("LIB", "LIBERTAS 7, S.A.", "A-46007449", "ES0137998A12", ("LIBERTAS 7", "LIB.MC", "LIBERTAS 7 SA", "LIBERTAS 7 SOCIEDAD ANONIMA")),
    CNMVIssuer("UNC", "UNION CATALANA DE VALORES, S.A.", "A-08483257", "ES0181222011", ("UNION CATALANA DE VALORES", "UNC.MC", "UNION CATALANA DE VALORES SA")),
    CNMVIssuer("AYC", "AYCO GRUPO INMOBILIARIO, S.A.", "A-28004240", "ES0152960045", ("AYCO", "AYC.MC", "AYCO GRUPO INMOBILIARIO SA")),
    CNMVIssuer("MON", "MOBILIARIA MONESA, S.A.", "A-08348740", "ES0164228019", ("MOBILIARIA MONESA", "MON.MC", "MOBILIARIA MONESA SA")),
    CNMVIssuer("IMC", "INMOCEMENTO, S.A.", "A-16367328", "ES0105836003", ("INMOCEMENTO", "IMC.MC", "INMOCEMENTO SA")),
    CNMVIssuer("ARM", "ARIMA REAL ESTATE SOCIMI, S.A.", "A-88130471", "ES0105376059", ("ARIMA", "ARM.MC", "ARIMA REAL ESTATE SOCIMI SA")),
    CNMVIssuer("GRE", "GRENERGY RENOVABLES, S.A.", "A-85130821", "ES0105079000", ("GRENERGY", "GRE.MC", "GRENERGY RENOVABLES SA")),
    CNMVIssuer("ADX", "AUDAX RENOVABLES, S.A.", "A-62338827", "ES0136463017", ("AUDAX", "ADX.MC", "AUDAX RENOVABLES SA")),
    CNMVIssuer("SOL", "SOLTEC POWER HOLDINGS, S.A.", "A-05556733", "ES0105513008", ("SOLTEC", "SOL.MC", "SOLTEC POWER HOLDINGS SA")),
    CNMVIssuer("REN", "RENTA CORPORACION REAL ESTATE, S.A.", "A-62385729", "ES0173365018", ("RENTA CORPORACION", "REN.MC", "RENTA CORPORACION REAL ESTATE SA")),
    CNMVIssuer("CEV", "COMPAÑIA ESPAÑOLA DE VIVIENDAS EN ALQUILER, S.A.", "A-28218543", "ES0132955008", ("CEVASA", "CEV.MC", "COMPAÑIA ESPAÑOLA DE VIVIENDAS EN ALQUILER SA")),
    CNMVIssuer("PRS", "PROMOTORA DE INFORMACIONES, S.A.", "A-28297059", "ES01717430J3", ("PRISA", "PRS.MC", "PROMOTORA DE INFORMACIONES SA")),
    CNMVIssuer("ISUR", "INMOBILIARIA DEL SUR, S.A.", "A-41002205", "ES0154653911", ("INMOBILIARIA DEL SUR", "ISUR.MC", "INMOBILIARIA DEL SUR SA")),
    CNMVIssuer("MVC", "METROVACESA, S.A.", "A-87471264", "ES0105122024", ("METROVACESA", "MVC.MC", "METROVACESA SA")),
    CNMVIssuer("COXG", "COX ABG GROUP, S.A.", "A-87073193", "ES0105848008", ("COX", "COXG.MC", "COX ABG GROUP SA")),
    CNMVIssuer("ISE", "INNOVATIVE SOLUTIONS ECOSYSTEM, S.A.", "A-28354132", "ES0143421073", ("INNOVATIVE SOLUTIONS", "ISE.MC", "INNOVATIVE SOLUTIONS ECOSYSTEM SA")),
    CNMVIssuer("ECO", "ECOLUMBER, S.A.", "A-43777119", "ES0127232017", ("ECOLUMBER", "ECO.MC", "ECOLUMBER SA")),
    CNMVIssuer("DESA", "DESARROLLOS ESPECIALES DE SISTEMAS DE ANCLAJE, S.A.", "A-58348038", "ES0126251018", ("DESA", "DESA.MC", "DESARROLLOS ESPECIALES DE SISTEMAS DE ANCLAJE SA")),
)


def _normalize(name: str) -> str:
    """Clave de comparacion exacta: mayusculas, SIN ACENTOS y SIN PUNTOS.

    El registro ESEF no normaliza las formas societarias: medido 2026-10-29
    en filings.xbrl.org, «COMPAÑÍA ESPAÑOLA DE VIVIENDAS EN ALQUILER S.A.»
    (tilde) y «GENERAL DE ALQUILER DE MAQUINARIA, S.A» (punto final ausente)
    no resolvian contra la tabla y sus emisores quedaban sin snapshot. Ambas
    direcciones se pliegan igual, asi que solo se fusionan formas del MISMO
    nombre; la resolucion sigue siendo por clave exacta, nunca parcial."""
    import unicodedata

    folded = "".join(
        c for c in unicodedata.normalize("NFKD", name.upper())
        if not unicodedata.combining(c)
    )
    return " ".join(folded.replace(",", " ").replace(".", "").split())


def resolve_issuer(query: str) -> CNMVIssuer | None:
    """Resolve a ticker/ISIN/NIF/exact legal name to a reviewed issuer.

    Returns None when the query matches nothing or matches ambiguously:
    unresolved or conflicting mappings stay unavailable, never guessed.
    Partial/free-text matches are intentionally NOT attempted.
    """
    q = _normalize(query)
    if not q:
        return None
    matches = []
    for issuer in REVIEWED_ISSUERS:
        keys = {issuer.ticker.upper(), issuer.isin.upper(), issuer.nif.upper().replace("-", "")}
        keys |= {_normalize(a) for a in issuer.aliases}
        keys.add(_normalize(issuer.legal_name))
        if q in keys or q.replace("-", "") == issuer.nif.upper().replace("-", ""):
            matches.append(issuer)
    return matches[0] if len(matches) == 1 else None


def issuer_for_nif(nif: str) -> CNMVIssuer | None:
    """Reverse lookup used when attributing CNMV filings to portfolio tickers."""
    normalized = nif.upper().replace("-", "")
    matches = [i for i in REVIEWED_ISSUERS if i.nif.upper().replace("-", "") == normalized]
    return matches[0] if len(matches) == 1 else None
