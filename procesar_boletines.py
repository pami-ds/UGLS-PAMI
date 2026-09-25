"""
procesar_boletines.py
=====================
Lee TODOS los boletines de PAMI (PDF) y reconstruye datos_ugl.json con las autoridades
VIGENTES de cada UGL y de cada Agencia (CAPs y Bocas de Atención incluidas), más el
historial completo de designaciones y ceses con su fecha.

No usa IA: lee el ÍNDICE de cada boletín, donde cada norma trae un resumen de una línea
con formato fijo, por ejemplo:

    RESOL-2026-1691-INSSJP-DE#INSSJP
    Designa y asigna al señor Esteban Maximiliano Herrera, las funciones de titular de la
    Agencia La Banda. UGL XIX - Santiago del Estero.

Reglas:
  * La fecha de cada evento es la del boletín (nombre del archivo dd-mm-aa.pdf).
  * Los eventos se aplican en orden cronológico (fecha y número de norma): una designación
    posterior reemplaza a la anterior en el mismo cargo; un "Limita" da de baja.
  * "Deja sin efecto la RESOL-..." anula el evento de esa norma.
  * El resultado se RECALCULA completo en cada corrida, así que es idempotente.

Uso:
    python procesar_boletines.py                 # usa boletines_historicos/ y boletines_diarios/
    python procesar_boletines.py carpeta1 carpeta2
"""
import os
import re
import sys
import json
import datetime
import unicodedata
import difflib

import pymupdf

DIR = os.path.dirname(os.path.abspath(__file__))
CARPETAS = sys.argv[1:] or [os.path.join(DIR, "boletines_historicos"), os.path.join(DIR, "boletines_diarios")]
SALIDA = os.path.join(DIR, "datos_ugl.json")
CACHE = os.path.join(DIR, "cache_indices.json")
DIRECTORIO = os.path.join(DIR, "directorio_agencias.json")
ORGANIGRAMA = os.path.join(DIR, "organigrama.json")

# --------------------------------------------------------------------------------------
# Catálogo de UGLs (número romano -> nombre y alias sin tildes)
# --------------------------------------------------------------------------------------
UGLS = [
    ("I", "Tucumán", ["TUCUMAN"]), ("II", "Corrientes", ["CORRIENTES"]), ("III", "Córdoba", ["CORDOBA"]),
    ("IV", "Mendoza", ["MENDOZA"]), ("V", "Bahía Blanca", ["BAHIA BLANCA"]),
    ("VI", "Capital Federal", ["CAPITAL FEDERAL", "CABA", "CIUDAD AUTONOMA"]), ("VII", "La Plata", ["LA PLATA"]),
    ("VIII", "San Martín", ["SAN MARTIN"]), ("IX", "Rosario", ["ROSARIO"]), ("X", "Lanús", ["LANUS"]),
    ("XI", "Mar del Plata", ["MAR DEL PLATA"]), ("XII", "Salta", ["SALTA"]), ("XIII", "Chaco", ["CHACO"]),
    ("XIV", "Entre Ríos", ["ENTRE RIOS", "PARANA"]), ("XV", "Santa Fe", ["SANTA FE"]), ("XVI", "Neuquén", ["NEUQUEN"]),
    ("XVII", "Chubut", ["CHUBUT"]), ("XVIII", "Misiones", ["MISIONES"]),
    ("XIX", "Santiago del Estero", ["SANTIAGO DEL ESTERO"]), ("XX", "La Pampa", ["LA PAMPA"]),
    ("XXI", "San Juan", ["SAN JUAN"]), ("XXII", "Jujuy", ["JUJUY"]), ("XXIII", "Formosa", ["FORMOSA"]),
    ("XXIV", "Catamarca", ["CATAMARCA"]), ("XXV", "La Rioja", ["LA RIOJA"]), ("XXVI", "San Luis", ["SAN LUIS"]),
    ("XXVII", "Río Negro", ["RIO NEGRO"]), ("XXVIII", "Santa Cruz", ["SANTA CRUZ"]), ("XXIX", "Morón", ["MORON"]),
    ("XXX", "Azul", ["AZUL"]), ("XXXI", "Junín", ["JUNIN"]), ("XXXII", "Luján", ["LUJAN"]),
    ("XXXIII", "Tierra del Fuego", ["TIERRA DEL FUEGO"]), ("XXXIV", "Concordia", ["CONCORDIA"]),
    ("XXXV", "San Justo", ["SAN JUSTO"]), ("XXXVI", "Río Cuarto", ["RIO CUARTO", "RIO IV"]),
    ("XXXVII", "Quilmes", ["QUILMES"]), ("XXXVIII", "Chivilcoy", ["CHIVILCOY"]),
]
ROMANOS = {u[0] for u in UGLS}


def sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def clave(s):
    return re.sub(r"\s+", " ", sin_tildes(str(s)).upper().replace("“", "").replace("”", "").replace('"', "")).strip()


def clave_lugar(s):
    """Clave para comparar nombres de Agencias: igual a claveLugar() de index.html."""
    k = clave(s)
    k = re.sub(r"^(AGENCIA|BOCA DE ATENCION|BOCA COMPLEMENTARIA|BOCA|C\.?\s?A\.?\s?P\.?|CENTRO DE ATENCION PERSONALIZADA)\s*", "", k)
    k = re.sub(r"\bPAMI\b|\bCABECERA\b", "", k)
    for a, b in [(r"\bPTO\b", "PUERTO"), (r"\bGOB\b", "GOBERNADOR"), (r"\bGRAL\b", "GENERAL"),
                 (r"\bCNEL\b", "CORONEL"), (r"\bSTA\b", "SANTA"), (r"\bVLLA\b", "VILLA")]:
        k = re.sub(a, b, k)
    return re.sub(r"[^A-Z0-9]", "", k.replace("Z", "S"))


CARGO_JEFE = "Titular de la UGL (Dirección Ejecutiva Local)"


def es_jefe(c):
    k = clave(c)
    return k in ("TITULAR", "TITULAR DE LA UGL") or bool(re.fullmatch(r"(TITULAR (DE LA )?)?DIRECCION EJECUTIVA( LOCAL)?", k)) \
        or bool(re.fullmatch(r"DIRECTORA? EJECUTIV[OA]( LOCAL)?", k))


def clave_cargo(s):
    if es_jefe(s) or s == CARGO_JEFE:
        return "JEFEUGL"
    k = clave(s)
    k = re.sub(r"\bDTO\.?\s", "DEPARTAMENTO ", k)
    k = re.sub(r"\bMAP\b", "MODELO DE ATENCION PERSONALIZADA", k)
    k = re.sub(r"\bADMINISTRATIV[AO]\b", "ADMINISTRATIVO", k)
    k = re.sub(r"^(REFERENTE|JEFE|JEFA|TITULAR)\s+(DE LA|DEL|DE)\s+", "", k)
    if re.search(r"\b(DIVISION|SECTOR|UNIDAD)\b", k):
        k = re.split(r",|\s+DEL?\s+DEPARTAMENTO", k)[0]
    k = re.sub(r"\b(DE|DEL|LA|LAS|LOS|EL|Y|TITULAR)\b", " ", k)
    k = k.replace("DIV.", "DIVISION").replace("DPTO.", "DEPARTAMENTO")
    return re.sub(r"[^A-Z0-9]", "", k)


CONECTORES = {"de", "del", "la", "las", "los", "y", "e", "el"}


def nombre_propio(s):
    out = []
    for i, p in enumerate(re.sub(r"\s+", " ", s).strip().split(" ")):
        low = p.lower()
        if i > 0 and low in CONECTORES:
            out.append(low)
        elif p.isupper() or p.islower() or re.search(r"[a-z][A-Z]", p):
            out.append(low[:1].upper() + low[1:])
        else:
            out.append(p)
    return " ".join(out)


# --------------------------------------------------------------------------------------
# 1) Lectura del índice de cada PDF (con caché para no releer)
# --------------------------------------------------------------------------------------
BULLET = re.compile(r"^[•●]\s*((?:R?ESOL|DI|RESFC|DISFC)-\d{4}-\d+-[A-Z\-]+[A-Z0-9]*#[A-Z]+)")
PAG = re.compile(r"^pag\.?\s*\d+\s*$", re.I)
RUIDO = re.compile(r"^(índice|indice|página|pagina|\d+|BOLET[IÍ]N DEL INSTITUTO.*|BUENOS AIRES,.*|Atención al afiliado)$", re.I)
ENCABEZADO = re.compile(r"^(RESOLUCIONES( CONJUNTAS)?|DISPOSICIONES( CONJUNTAS)?|Índice|Dirección Ejecutiva|"
                        r"Subdirección Ejecutiva|Coordinación Ejecutiva|Secretar[ií]a .*|Gerencia .*|Subgerencia .*|"
                        r"Unidad .*|Hospital .*|Direcci[oó]n .*|UGL [IVXL]+\s*[-–].*)$")


def leer_indice(ruta):
    """Lee solo el índice del boletín.
    Una viñeta es del índice si trae 'pag. N' (en la misma línea o en las 2 siguientes).
    La primera viñeta seguida de 'CIUDAD, dd MES. aaaa' marca el inicio del cuerpo."""
    doc = pymupdf.open(ruta)
    lineas = []
    try:
        for n, pagina in enumerate(doc):
            if n > 25:
                break
            lineas += [l.strip() for l in pagina.get_text(sort=True).splitlines() if l.strip()]
    finally:
        doc.close()
    entradas, actual = [], None
    for i, l in enumerate(lineas):
        m = BULLET.match(l)
        if m:
            siguientes = lineas[i + 1:i + 3]
            if re.search(r"pag\.?\s*\d+\s*$", l, re.I) or any(PAG.match(x) for x in siguientes):
                actual = {"norma": m.group(1), "txt": ""}
                entradas.append(actual)
            else:
                if any(re.match(r"^[A-ZÁÉÍÓÚÑ .]+,\s*\d{1,2}\s+[A-Z]{3}", x) for x in siguientes):
                    break                               # empezó el cuerpo del boletín
                actual = None
            continue
        if actual is None or PAG.match(l) or RUIDO.match(l) or re.search(r"[íi]ndice\s+p[áa]gina", l, re.I):
            continue
        if ENCABEZADO.match(l) and not l.endswith("."):
            actual = None
            continue
        if l.upper().startswith("VISTO"):
            actual = None
            continue
        actual["txt"] = (actual["txt"] + " " + l).strip()
    return entradas


# --------------------------------------------------------------------------------------
# 1b) Formato viejo (2020-2023): índice sin viñetas y resúmenes sin nombres.
#     El nombre de la persona se toma del ARTÍCULO de la propia resolución.
# --------------------------------------------------------------------------------------
NORMA_ID = r"(?:R?ESOL|DI|RESFC|DISFC)-\d{4}-\d+-[A-Z\-]+[A-Z0-9]*#[A-Z]+"
RX_IDX_NORMA = re.compile(r"^\s*(" + NORMA_ID + r")\s*$")
RX_IDX_PAG = re.compile(r"\.*\s*p[áa]g\.?\s*\d+\s*$", re.I)
RX_BLOQUE_RUIDO = re.compile(r"^\s*(p[áa]gina \d+\s*[íi]ndice|Año [XVIL]+ - N°|BUENOS AIRES, [A-Z][a-zé]+ \d|BOLET[IÍ]N\s*DEL INSTITUTO|"
                             r"DESCARGUE LA|PARA JUBILADOS Y PENSIONADOS\s*$)", re.I)
RELEVANTE = re.compile(r"(titular|funci[oó]n|limita|asigna|designa|deja sin efecto|crea (la|el) (boca|cap|agencia)|firma)", re.I)
RX_ARTICULO = re.compile(r"ART[IÍÌ]CULO\s*\d+\s*[°º]?\s*\.?\s*[-–]?\s*", re.I)
VERBOS = [(r"^Designar y asignar", "Designa y asigna"), (r"^Asignar", "Asigna"), (r"^Limitar", "Limita"),
          (r"^Designar", "Designa"), (r"^Dejar sin efecto", "Deja sin efecto"), (r"^Delegar", "Delega"),
          (r"^Crear", "Crea"), (r"^Trasladar", "Traslada")]


def _bloques(doc, desde=0, hasta=None):
    out = []
    for n, pagina in enumerate(doc):
        if n < desde or (hasta is not None and n >= hasta):
            continue
        for b in pagina.get_text("blocks"):
            t = b[4].strip()
            if t and not RX_BLOQUE_RUIDO.match(t):
                out.append((n, b[0], t))
    return out


def adaptar_articulo(a):
    """'Limitar, a partir de ..., a la trabajadora X (Legajo ..), las funciones de ...' -> 'Limita a la trabajadora X, las funciones de ...'"""
    a = re.sub(r"\s+", " ", a).strip()
    a = re.sub(r"([a-záéíóúñ])- ([a-záéíóúñ])", r"\1\2", a)
    a = re.sub(r"\s*\([^)]*\)", "", a)
    a = re.sub(r"\b(al|del) (Doctor|Dr\.|Licenciado|Lic\.|Contador|Cdor\.|Ingeniero|Ing\.|Arquitecto|Abogado)\s", r"\1 señor ", a)
    a = re.sub(r"\b(a la|de la) (Doctora|Dra\.|Licenciada|Lic\.|Contadora|Cdora\.|Ingeniera|Ing\.|Arquitecta|Abogada)\s", r"\1 señora ", a)
    a = re.sub(r",?\s*a partir (?:de|del) (?:la fecha de (?:su )?notificaci[oó]n|(?:el )?dictado de la presente|la fecha de la presente|[^,]{0,60}),", "", a, flags=re.I)
    a = re.sub(r",?\s*(?:y )?con car[aá]cter (?:transitorio|interino)[^,]*,", ",", a, flags=re.I)
    a = re.sub(r"\s*,?\s*(correspondiendo|con una carga|con un r[ée]gimen|conforme|quedando|en el Tramo|seg[uú]n lo|en virtud|como as[ií] tambi[ée]n|en los t[ée]rminos|que le fuer[ao]n?|manteniendo|y el adicional)\b.*$", "", a, flags=re.I)
    for rx, rep in VERBOS:
        if re.match(rx, a, re.I):
            a = re.sub(rx, rep, a, count=1, flags=re.I).replace(rep + ",", rep, 1)
            break
    # 'Asigna las funciones de X, a la señora Y' -> 'Asigna a la señora Y, las funciones de X'
    m = re.match(r"^(Asigna|Designa y asigna|Designa|Limita)\s+(las funciones .+?),?\s+((?:al|a la|a)\s+(?:señor|señora|trabajador|trabajadora|agente)\s+.+)$", a)
    if m:
        a = f"{m.group(1)} {m.group(3)}, {m.group(2)}"
    return a.strip(" ,")


def leer_indice_viejo(ruta):
    doc = pymupdf.open(ruta)
    try:
        # índice: bloques de la columna izquierda de las primeras páginas
        indice, pendiente = [], None
        for n, x, t in _bloques(doc, 0, 3):
            if x > 200 or re.search(r"\n\s*[A-ZÁÉÍÓÚÑ ]+,\s*\d{1,2}\s+[A-Z]{3}", t):
                continue
            for l in [s.strip() for s in t.splitlines() if s.strip()]:
                l = l.lstrip("•● ").strip()
                m = RX_IDX_NORMA.match(l)
                if m:
                    pendiente = {"norma": m.group(1), "resumen": ""}
                    continue
                if pendiente is not None:
                    pendiente["resumen"] = (pendiente["resumen"] + " " + l).strip()
                    if RX_IDX_PAG.search(l):
                        pendiente["resumen"] = RX_IDX_PAG.sub("", pendiente["resumen"]).rstrip(" .")
                        indice.append(pendiente)
                        pendiente = None
        if not indice:
            return []
        # cuerpo completo
        texto = "\n".join(t for _, _, t in _bloques(doc))
    finally:
        doc.close()

    entradas = []
    for ent in indice:
        if not RELEVANTE.search(ent["resumen"]):
            continue
        rx = re.compile(re.escape(ent["norma"]) + r"\s*\n\s*[A-ZÁÉÍÓÚÑ ]+,\s*\d{1,2}\s")
        m = rx.search(texto)
        txts = []
        if m:
            cuerpo = texto[m.end():]
            fin = re.search(re.escape(ent["norma"]) + r"\s*\n", cuerpo)
            cuerpo = cuerpo[:fin.start()] if fin else cuerpo[:20000]
            r = re.search(r"\b(RESUELVEN?|DISPONEN?)\s*:?\s*\n", cuerpo)
            parte = cuerpo[r.end():] if r else cuerpo
            articulos = [a for a in RX_ARTICULO.split(parte) if a.strip()]
            for a in articulos[:6]:
                ad = adaptar_articulo(a)
                if re.match(r"^(Asigna|Limita|Designa y asigna|Deja sin efecto|Delega|Traslada)", ad) and \
                        (re.search(r"funci[oó]n|titular|firma", ad, re.I) or ad.startswith("Deja")):
                    if interpretar(ad) or (ad.startswith("Deja") and not txts):
                        txts.append(ad)
                elif re.match(r"^Crea (la|el) (Boca|CAP|Agencia)", ad):
                    txts.append(ad)
        for txt in (txts or [ent["resumen"]]):
            entradas.append({"norma": ent["norma"], "txt": txt, "resumen": ent["resumen"]})
    return entradas


def fecha_de_archivo(nombre):
    m = re.match(r"(\d{2})-(\d{2})-(\d{2})", nombre)
    if not m:
        return None
    d, mth, y = map(int, m.groups())
    return datetime.date(2000 + y, mth, d).isoformat()


# --------------------------------------------------------------------------------------
# 2) Interpretación de cada resumen
# --------------------------------------------------------------------------------------
RX_UGL = re.compile(r"(?:\bUG\s?[Ll](?=[\sIVXLl\-–])|Unidad de Gesti[oó]n Local)\s*(?:Local\s*)?[-–]?\s*([IVXLl][IVXLl\s\-–]*?)\s*(?:(?:[-–—,.]\s*|\s+)([A-ZÁÉÍÓÚa-záéíóúñÑ][^.,;]{2,40})|[.,;]|$)")
RX_PERSONA = re.compile(
    r"(?:\b(?:al|a la|a|la|en el|en la)\s+|\s)(?:trabajador(?:a)?|señor(?:a)?|agente|Dr\.?|Dra\.?)\s+"
    r"(.+?)(?=,|\s+las funciones|\s+funciones|\s+titular\b|\.\s|\s+la firma|\s+la fima|\s+a la sede|\s+al\s|\s+a la\s|\s+a\s|\s+para\s|\s+y\s+traslad|$)")
RX_PERSONA2 = re.compile(
    r"^(?:Limita|Limíta|Asigna|Asígna|Designa y asigna)\s+(?:a|al|a la)\s+((?:[A-ZÁÉÍÓÚÑ][\wáéíóúñ’']+\s*){2,6}?)"
    r"(?=,|\s+las funciones|\s+funciones|\s+titular\b)")
RX_DEP = re.compile(r"\b(CAP|C\.A\.P\.|(?<=del )CAL?|Centro de Atenci[oó]n Personalizad[ao]|Agencia|Ag\.|"
                    r"[Bb]oca de [Aa]tenci[oó]n|Boca)(?=[\s,.])[,.]?\s+"
                    r"(?:Cabecera\s+)?(?:(?:Pami|PAMI)\s+)?(?:(?:de|del|el|la)\s+(?=[A-ZÁÉÍÓÚ0-9]))?(.+)$")
PUNTO = r"(?<!\b[A-Z])(?<!\bAg)(?<!\bDr)(?<!\bCAP)(?<!\bGral)\.(?:\s|(?=[A-Z]))"     # fin de oración, pero no 'Juan B. Alberdi'



def detectar_ugl(txt):
    # Si después de 'UGL' aparece el nombre de una UGL, manda el nombre: corrige números mal tipeados
    # como 'UGL XXX- VIII – Chivilcoy' (que se leería como XXX - Azul).
    for m in re.finditer(r"(?:\bUG\s?[Ll]|Unidad de Gesti[oó]n Local)", txt):
        if re.search(r"\bde\s+$", txt[:m.start()]):      # 'Coordinación de UGL ...' es Nivel Central, no una UGL
            continue
        tramo = clave(txt[m.end():m.end() + 45])
        mejor = None
        for num, _, alias in UGLS:
            for a in alias:
                i = re.search(r"\b" + a + r"\b", tramo)
                if i and (mejor is None or i.start() < mejor[1] or (i.start() == mejor[1] and len(a) > mejor[2])):
                    mejor = (num, i.start(), len(a))
        if mejor:
            return mejor[0]
    for m in RX_UGL.finditer(txt):
        nombre = clave(m.group(2) or "")
        mejor = None
        for num, _, alias in UGLS:
            for a in alias:
                if nombre and nombre.startswith(a) and (mejor is None or len(a) > mejor[1]):
                    mejor = (num, len(a))
        if mejor:
            return mejor[0]
        romano = re.sub(r"[\s\-–]", "", m.group(1)).upper()
        if romano in ROMANOS:
            return romano
        primero = re.split(r"[\s\-–]+", m.group(1).strip())[0].upper()
        if primero in ROMANOS:
            return primero
    return None


def limpiar_cargo(c):
    c = re.sub(r"\s+", " ", c).strip(" .,;-–")
    c = re.sub(r"\s+(de la|del|de|en la|en el)\s*$", "", c, flags=re.I)
    c = re.sub(r"\s*[,.]?\s*dependiente de.*$", "", c, flags=re.I)
    return c.strip(" .,;-–")


def separar_dependencia(cargo):
    """'titular del CAP Villa Ocampo' -> (dep='Villa Ocampo', tipo='CAP', rol='Titular')"""
    partes = re.split(PUNTO, cargo)
    primera = re.split(r"\s+y\s+(?:autoriza|traslad|asign|limit|otorga)", partes[0])[0]
    m = RX_DEP.search(primera)
    base = primera
    if not m and len(partes) > 1:                 # 'Referente Moeit. Agencia Berazategui'
        m2 = re.match(r"\s*(Agencia|Ag\.)\s+(.+)$", " ".join(partes[1:2]))
        if m2:
            base = primera + " " + " ".join(partes[1:2]).strip()
            m = RX_DEP.search(base)
    if not m:
        return None, None, primera
    t = sin_tildes(m.group(1)).lower()
    tipo = "Boca de Atención" if t.startswith("boca") else "Agencia" if t.startswith("ag") else "CAP"
    dep = re.split(r"\s*(?:,|\s-\s|\s–\s)|" + PUNTO, m.group(2))[0]
    dep = re.sub(r"\s+(de la|del|de)$", "", dep.strip(" .,;"), flags=re.I).strip()
    rol = limpiar_cargo(base[:m.start()])
    if rol.lower() in ("titular", "titular en", ""):
        rol = "Titular"
    else:
        rol = re.sub(r"^titular\s+(de la|del|de)\s+", "", rol, flags=re.I)
    if re.fullmatch(r"(?i)(pami\s*)?\d+", dep):
        dep = "PAMI " + re.sub(r"\D", "", dep)
    elif dep.isupper() or dep.islower():
        dep = nombre_propio(dep)
    return dep, tipo, rol[:1].upper() + rol[1:]


def normalizar_norma(n):
    m = re.search(r"(RESOL|DI|RESFC|DISFC)-(\d{4})-(\d+)-I?N+S+J?P-([A-Z0-9]+)", n.replace("#", "-"))
    return f"{m.group(1)}-{m.group(2)}-{int(m.group(3))}-{m.group(4)}" if m else n


def interpretar(txt):
    """Devuelve lista de eventos (sin fecha) a partir del resumen de una norma."""
    t = re.sub(r"\s+", " ", txt).strip()
    t = re.sub(r"([a-záéíóúñ])-\s+([a-záéíóúñ])", r"\1\2", t)      # 'Teso- rería' -> 'Tesorería'
    t = t.replace("titulardel", "titular del")
    b = sin_tildes(t).lower()
    ev = []

    if b.startswith("deja sin efecto"):
        for m in re.finditer(r"(?:RESOL|DI|RESFC|DISFC)-\d{4}-\d+-[A-Z]+-[A-Z0-9#]+", t):
            ev.append({"accion": "anula", "ref": normalizar_norma(m.group(0))})
        return ev

    ugl = detectar_ugl(t)

    if b.startswith("crea la boca") or b.startswith("crea el cap") or b.startswith("crea la agencia"):
        m = re.search(r"Crea (?:la|el) (Boca de Atenci[oó]n|CAP|Agencia)\s+(.+?),?\s+en el [aá]mbito", t)
        if m:
            ev.append({"accion": "crea", "ugl": ugl, "dependencia": m.group(2).strip(), "tipo": m.group(1)})
        return ev

    # Normas que no son cambios de autoridades de una persona
    if re.match(r"^(asigna (las )?funciones (a|al|de) (los|personal|el personal)|asigna personal|asigna las funciones (de|del|al) personal)", b):
        return ev
    if re.search(r"para (prestar servicios|desempenar tareas)|carga horaria|(autoriza|aprueba) (la|el) contrat|renovacion del contrato|reduccion de la jornada|rescision", b):
        return ev

    pm = RX_PERSONA.search(t) or RX_PERSONA2.search(t)
    if not pm:
        return ev
    persona = nombre_propio(pm.group(1).strip(" ,."))
    if len(persona.split()) < 2 or len(persona) > 60:
        return ev

    es_alta = bool(re.search(r"\basign", b)) and "funcion" in b
    es_baja = b.startswith("limit") and not es_alta
    es_firma = b.startswith("delega") and ("firma" in b or "fima" in b) and ugl is not None

    cargo = None
    mc = re.search(r"funciones? (?:de|del)\s*(.+)", t.replace("titulardel", "titular del")) or re.search(r"\b(titular (?:de la|del|de)\s+.+)", t)
    if mc:
        resto = mc.group(1)
        resto = re.split(r"(?:[.,;]?\s*(?:de la\s+)?(?:\bUG\s?[Ll](?=[\sIVXLl\-–])|Unidad de Gesti[oó]n Local)|\.\s*$|\s+y\s+traslad)", resto)[0]
        cargo = limpiar_cargo(resto)
        if cargo.lower().startswith("la ") or cargo.lower().startswith("el "):
            cargo = cargo[3:]
    if es_firma:
        cargo = "Firma delegada de la UGL"
        es_alta = True

    base = {"ugl": ugl, "persona": persona}
    if cargo:
        dep, tipo, rol = separar_dependencia(cargo)
        cargo_final = rol if dep else cargo[:1].upper() + cargo[1:]
        if not dep and (es_jefe(cargo_final) or clave(cargo_final) == "TITULAR DE"):
            cargo_final = CARGO_JEFE
        base.update({"dependencia": dep, "tipo_dep": tipo, "cargo": cargo_final})
    if es_alta and cargo:
        ev.append(dict(base, accion="alta"))
    elif es_baja:
        ev.append(dict(base, accion="baja"))       # sin cargo => baja de todos sus cargos
    return ev


# --------------------------------------------------------------------------------------
# 3) Aplicación cronológica
# --------------------------------------------------------------------------------------
def cargar_directorio():
    try:
        with open(DIRECTORIO, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        return {}
    idx = {}
    for num, lista in d.items():
        for e in lista:
            if e.get("tipo") == "ugl":
                continue
            for k in {clave_lugar(e["nombre"]), clave_lugar(e.get("localidad", ""))}:
                if k:
                    idx.setdefault(k, set()).add(num)
    return idx


# Nombres que existen en muchas provincias: no se corrige la UGL por coincidencia con el listado
NOMBRES_GENERICOS = {"SANTA ROSA", "SUR", "NORTE", "CENTRO", "OESTE", "ESTE", "SAN JOSE", "SAN MARTIN", "BELGRANO",
                     "SAN JUAN", "SAN PEDRO", "SAN ANTONIO", "SAN LORENZO", "LA PAZ", "VILLA NUEVA", "CONCEPCION"}


def construir(eventos, meta):
    dir_idx = cargar_directorio()
    dir_por_ugl = {}
    for k, nums in dir_idx.items():
        for n in nums:
            dir_por_ugl.setdefault(n, set()).add(k)
    correcciones = []
    anuladas = {e["ref"] for e in eventos if e["accion"] == "anula"}
    ugls = {num: {"nombre": nom, "autoridades": {}, "agencias": {}, "historial": []} for num, nom, _ in UGLS}
    sin_ugl = []

    def dep_obj(u, nombre, tipo):
        k = clave_lugar(nombre)
        if k not in u["agencias"]:
            # Variantes de escritura: 'Daireux'/'Daireaux', 'Lamadrid'/'General Lamadrid'
            for k2 in u["agencias"]:
                if (len(k) >= 6 and len(k2) >= 6 and (k.endswith(k2) or k2.endswith(k))) or \
                        difflib.SequenceMatcher(None, k, k2).ratio() >= 0.88:
                    k = k2
                    break
        a = u["agencias"].setdefault(k, {"nombre": nombre, "tipo_original": tipo or "Agencia", "autoridades": {}})
        if not (len(a["nombre"]) > len(nombre) and clave_lugar(a["nombre"]).endswith(clave_lugar(nombre))):
            a["nombre"] = nombre                         # la grafía más reciente (salvo que sea una versión recortada)
        if tipo and a["tipo_original"] == "Agencia" and tipo != "Agencia":
            a["tipo_original"] = tipo
        return a

    for e in sorted(eventos, key=lambda x: (x["fecha"], x["orden"])):
        if e["accion"] == "anula" or e["norma_n"] in anuladas:
            continue
        num = e.get("ugl")
        if not num and e.get("dependencia"):
            cand = dir_idx.get(clave_lugar(e["dependencia"]), set())
            num = next(iter(cand)) if len(cand) == 1 else None
        if not num:
            sin_ugl.append(e)
            continue
        # Control contra el listado oficial: si la dependencia existe en UNA sola UGL y no en la que dice
        # el boletín, el boletín tiene el número de UGL mal (p. ej. 'CAP Monte Quemado, UGL XXXII - Luján').
        if e.get("dependencia"):
            kd = clave_lugar(e["dependencia"])
            cand = dir_idx.get(kd, set())
            if len(cand) == 1 and num not in cand and kd not in {clave_lugar(x) for x in NOMBRES_GENERICOS} and \
                    not any(difflib.SequenceMatcher(None, kd, k2).ratio() >= 0.88 for k2 in dir_por_ugl.get(num, ())):
                correcciones.append((e["fecha"], e["norma"], e["dependencia"], num, next(iter(cand))))
                num = next(iter(cand))
        u = ugls[num]
        ref = {"fecha": e["fecha"], "norma": e["norma"]}
        hist = {"fecha": e["fecha"], "norma": e["norma"], "accion": e["accion"], "persona": e.get("persona"),
                "cargo": e.get("cargo"), "agencia": e.get("dependencia")}

        if e["accion"] == "crea":
            dep_obj(u, e["dependencia"], "Boca de Atención" if "Boca" in e["tipo"] else e["tipo"])["creada"] = ref
            hist["cargo"] = "Creación de la dependencia"
            u["historial"].append(hist)
            continue

        destino = dep_obj(u, e["dependencia"], e.get("tipo_dep"))["autoridades"] if e.get("dependencia") else u["autoridades"]
        if e["accion"] == "alta":
            kc = clave_cargo(e["cargo"])
            # Traslado implícito: si la persona ya era titular de OTRA agencia de esta UGL, deja ese cargo
            if e.get("dependencia") and e["cargo"] == "Titular" or "traslad" in e["resumen"].lower():
                kp = clave(e["persona"])
                for a in u["agencias"].values():
                    if a["autoridades"] is destino:
                        continue
                    for kc2 in [x for x, v in a["autoridades"].items() if clave(v["persona"]) == kp]:
                        del a["autoridades"][kc2]
            destino[kc] = {"cargo": e["cargo"], "persona": e["persona"], "desde": e["fecha"], "norma": e["norma"]}
        elif e["accion"] == "baja":
            kp = clave(e["persona"])
            objetivos = [u["autoridades"]] + [a["autoridades"] for a in u["agencias"].values()]
            for aut in objetivos:
                for kc in list(aut):
                    if clave(aut[kc]["persona"]) == kp and (not e.get("cargo") or kc == clave_cargo(e["cargo"]) or aut is destino):
                        del aut[kc]
        u["historial"].append(hist)

    # Salida
    salida = {"_formato": 2, "_meta": meta, "ugls": {}}
    for num, u in ugls.items():
        salida["ugls"][num] = {
            "nombre": u["nombre"],
            "autoridades": sorted(u["autoridades"].values(), key=lambda a: (a["cargo"] != CARGO_JEFE, a["cargo"])),
            "agencias": {a["nombre"]: {"tipo_original": a["tipo_original"],
                                       "autoridades": sorted(a["autoridades"].values(), key=lambda x: x["cargo"]),
                                       **({"creada": a["creada"]} if "creada" in a else {})}
                         for a in sorted(u["agencias"].values(), key=lambda a: a["nombre"])},
            "historial": sorted(u["historial"], key=lambda h: h["fecha"], reverse=True),
        }
    salida["_meta"]["eventos_sin_ugl"] = len(sin_ugl)
    salida["_meta"]["ugl_corregida_por_listado"] = [
        {"fecha": f, "norma": n, "agencia": d, "boletin_decia": a, "corregida_a": b} for f, n, d, a, b in correcciones]
    for f, n, d, a, b in correcciones:
        print(f"[CORRECCION] {d}: el boletín {f} ({n}) dice UGL {a}, el listado oficial la ubica en UGL {b}")
    return salida, sin_ugl


# --------------------------------------------------------------------------------------
# 4) Nivel Central: ubica cada designación sin UGL en una unidad del organigrama
# --------------------------------------------------------------------------------------
def cargar_organigrama():
    try:
        with open(ORGANIGRAMA, encoding="utf-8") as f:
            return json.load(f)["unidades"]
    except Exception:
        return []


def cargo_completo(e):
    """Recupera el cargo completo desde el resumen (sin cortar en 'UGL')."""
    t = re.sub(r"\s+", " ", e["resumen"])
    t = re.sub(r"([a-záéíóúñ])-\s+([a-záéíóúñ])", r"\1\2", t)
    m = re.search(r"funciones? (?:de|del)\s*(.+)", t) or re.search(r"\b(titular (?:de la|del|de)\s+.+)", t)
    if not m:
        return e.get("cargo") or ""
    c = m.group(1)
    c = re.split(r"\s+y\s+(?:traslad|autoriza|asign|limit)", c)[0]
    return c.strip(" .,;")


def ubicar_central(cargo, unidades):
    """Devuelve (id_unidad, cargo_a_mostrar) o (None, cargo)."""
    k = clave(cargo)
    k = re.sub(r"^TITULAR\s+(DE LA|DEL|DE)\s+", "", k)
    base = re.split(r"[.,]|\s+DEPENDIENTE", k)[0].strip()
    base = re.sub(r"^DIV\.? ", "DIVISION ", re.sub(r"^DTO\.? ", "DEPARTAMENTO ", base))
    nombres = [(u, clave(u["nombre"])) for u in unidades]
    # 1) El cargo ES la unidad (titular de la unidad)
    for u, ku in nombres:
        if base == ku or difflib.SequenceMatcher(None, base, ku).ratio() >= 0.9:
            return u["id"], "Titular"
    visible = re.sub(r"^titular\s+(de la|del|de)\s+", "", cargo, flags=re.I)
    visible = re.sub(r"[.,]?\s*dependiente de.*$", "", visible, flags=re.I).strip(" .,")
    # 2) Área interna que menciona a su unidad ("... de la Subgerencia Operativa de UGL Zona 2")
    mejor = None
    for u, ku in nombres:
        if len(ku) > 14 and ku in k and ku != base and (mejor is None or len(ku) > len(mejor[1])):
            mejor = (u, ku)
    if mejor:
        return mejor[0]["id"], visible
    # 3) Sigla al final: 'Departamento Penalidades. GAJ'
    ms = re.search(r"(?:[.,]\s*|\s)([A-Z][A-Za-z]{1,6})\.?\s*$", cargo.strip())
    if ms:
        sig = ms.group(1).upper()
        for u, _ in nombres:
            if sig not in ("DE", "SE", "CE") and sig in [x.upper() for x in u.get("siglas", [])]:
                return u["id"], re.sub(r"[.,]?\s*[A-Z][A-Za-z]{1,6}\.?\s*$", "", visible).strip(" .,")
    # 4) Palabras clave (hospitales propios, etc.)
    for u, _ in nombres:
        for c in u.get("claves", []):
            if re.search(r"\b" + c + r"\b", k):
                return u["id"], visible
    return None, visible


def construir_central(eventos):
    unidades = cargar_organigrama()
    anuladas = {e["ref"] for e in eventos if e["accion"] == "anula"}
    estado = {u["id"]: {} for u in unidades}
    historial = {u["id"]: [] for u in unidades}
    otros, otros_hist = {}, []
    for e in sorted(eventos, key=lambda x: (x["fecha"], x["orden"])):
        if e["accion"] not in ("alta", "baja") or e.get("ugl") or e.get("dependencia") or e["norma_n"] in anuladas:
            continue
        cargo = cargo_completo(e) if (e.get("cargo") or e["accion"] == "alta") else ""
        cargo = re.sub(r"^(L|Tutlar del|Titular del?)\s+(?=[A-Z])", "", cargo)
        e = dict(e, persona=re.sub(r"^(Al|A la)\s+Se[ñn]or(a)?\s+", "", e["persona"], flags=re.I))
        uid, visible = ubicar_central(cargo, unidades) if cargo else (None, "")
        destino = estado[uid] if uid else otros
        h = {"fecha": e["fecha"], "norma": e["norma"], "accion": e["accion"], "persona": e["persona"], "cargo": visible or None}
        (historial[uid] if uid else otros_hist).append(h)
        if e["accion"] == "alta" and visible:
            destino[clave_cargo(visible) or "TITULAR"] = {"cargo": visible[:1].upper() + visible[1:], "persona": e["persona"], "desde": e["fecha"], "norma": e["norma"]}
        elif e["accion"] == "baja":
            kp = clave(e["persona"])
            for aut in list(estado.values()) + [otros]:
                for kc in list(aut):
                    if clave(aut[kc]["persona"]) == kp and (not visible or aut is destino):
                        del aut[kc]
    salida = {}
    for u in unidades:
        if estado[u["id"]] or historial[u["id"]]:
            salida[u["id"]] = {
                "autoridades": sorted(estado[u["id"]].values(), key=lambda a: (a["cargo"] != "Titular", a["cargo"])),
                "historial": sorted(historial[u["id"]], key=lambda x: x["fecha"], reverse=True)}
    return salida, {"autoridades": sorted(otros.values(), key=lambda a: a["cargo"]),
                    "historial": sorted(otros_hist, key=lambda x: x["fecha"], reverse=True)}


def main():
    try:
        with open(CACHE, encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}

    archivos = []
    for c in CARPETAS:
        if os.path.isdir(c):
            archivos += [os.path.join(c, f) for f in os.listdir(c) if f.lower().endswith(".pdf")]
    print(f"[INFO] {len(archivos)} boletines encontrados")

    eventos, fechas = [], []
    for ruta in sorted(archivos):
        nombre = os.path.basename(ruta)
        fecha = fecha_de_archivo(nombre)
        if not fecha:
            print(f"[AVISO] Nombre sin fecha dd-mm-aa, se omite: {nombre}")
            continue
        clave_cache = f"{nombre}:{os.path.getsize(ruta)}"
        if clave_cache not in cache:
            try:
                # en los boletines viejos los resúmenes del índice no traen nombres: se leen los artículos de cada norma
                # (formato viejo, hasta mediados de 2024). Se usa la lectura que encuentra más designaciones.
                nuevo, viejo = leer_indice(ruta), leer_indice_viejo(ruta)
                util = lambda ents: sum(1 for x in ents if interpretar(x["txt"]))
                cache[clave_cache] = viejo if util(viejo) > util(nuevo) else (nuevo or viejo)
            except Exception as ex:
                print(f"[ERROR] {nombre}: {ex}")
                continue
        fechas.append(fecha)
        for i, ent in enumerate(cache[clave_cache]):
            for ev in interpretar(ent["txt"]):
                mnum = re.match(r"^[A-Z]+-\d{4}-(\d+)", ent["norma"])
                ev.update({"fecha": fecha, "orden": (int(mnum.group(1)) if mnum else 0, i),
                           "norma": ent["norma"], "norma_n": normalizar_norma(ent["norma"]),
                           "boletin": nombre, "resumen": ent.get("resumen") or ent["txt"]})
                eventos.append(ev)

    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    meta = {"generado": datetime.datetime.now().isoformat(timespec="seconds"),
            "boletines": len(fechas), "desde": min(fechas) if fechas else None, "hasta": max(fechas) if fechas else None,
            "eventos": len(eventos)}
    datos, sin_ugl = construir(eventos, meta)
    datos["nivel_central"], datos["nivel_central_otros"] = construir_central(eventos)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=1)

    n_aut = sum(len(u["autoridades"]) + sum(len(a["autoridades"]) for a in u["agencias"].values()) for u in datos["ugls"].values())
    n_ag = sum(len(u["agencias"]) for u in datos["ugls"].values())
    print(f"[OK] {meta['boletines']} boletines ({meta['desde']} a {meta['hasta']}) · {len(eventos)} eventos · "
          f"{n_ag} agencias · {n_aut} autoridades vigentes · {len(sin_ugl)} eventos sin UGL identificable")


if __name__ == "__main__":
    main()
