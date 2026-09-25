"""
Genera datos_extra.json a partir de catalogo_pami.json (resúmenes del buscador de www.pami.org.ar/boletin-oficial).

Tres tipos de información que no son cargos de conducción:
  - estructura : creación, supresión o cambio de nombre de agencias, CAPs, bocas y áreas de las UGL
  - inmuebles  : alquileres, renovaciones, búsquedas de sede, obras y mudanzas
  - personal   : personas que ingresan a trabajar (designación o contratación), traslados y egresos

Uso:  python procesar_catalogo.py
"""
import json
import os
import re

from procesar_boletines import detectar_ugl, nombre_propio, clave_lugar

BASE = os.path.dirname(os.path.abspath(__file__))
ENTRADA = os.path.join(BASE, "catalogo_pami.json")
SALIDA = os.path.join(BASE, "datos_extra.json")

RX_ID = re.compile(r"^(?:RESOL|DI|DISFC|RESFC)-\d{4}-\d+-[A-Z0-9#\-]+\.?\s*")
RX_DEP = re.compile(
    r"\b(Agencia|Centro de Atenci[oó]n Personalizad[ao]|CAP|C\.A\.P\.|Boca de Atenci[oó]n|UDAI)\s+"
    r"(?:N[°º]\s*)?(?:denominad[oa]\s+)?[\"“]?([A-ZÁÉÍÓÚÑ0-9][^,;.()“”\"]{0,40}?)[\"”]?"
    r"(?=\s*[,;.(]|\s+(?:de la|del|dependiente|ubicad|sit[oa]|en el|en la|y\s|la que|el que|que\s|UGL|Unidad)|$)")
GENERICOS = {"", "DE", "DEL", "LA", "EL", "APTO", "APTA", "Y", "PAMI", "N", "NUEVA", "NUEVO", "DE ATENCION"}
TIPO_DEP = {"agencia": "Agencia", "udai": "Agencia", "boca": "Boca de Atención"}

RX_PERSONA = re.compile(
    r"(?:\b(?:al|a la|de la|del|el|la|a)\s+)(?:se[ñn]ora?|trabajadora?|agente|dependiente|emplead[oa]|doctora?|Dra?\.|"
    r"licenciad[oa]|Lic\.|contador(?:a)?|C\.?P\.?N\.?|ingenier[oa]|Ing\.)\s+"
    r"([A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñü’'´\-\. ]{3,60}?)(?=\s*\(|,|\s+para\s|\s+en\s|\s+a\s|\s+quien|\s+con\s|\s+de\s+la\s|\.|$)")

RX_ESTRUCTURA = re.compile(r"^(Cre[oóa]r?|Supri\w*|Sustitu\w*\s+la\s+denominaci|Modific\w*\s+la\s+denominaci|Cambi\w*\s+la\s+denominaci|"
                           r"Desafect\w*\s+(?:la|el)\s+(?:Agencia|Boca|Centro|CAP)|Transform\w*|Fusion\w*|Aprob\w*\s+la\s+(?:estructura|apertura|creaci)|Dispus\w*\s+(?:el\s+cierre|la\s+apertura))", re.I)
RX_INMUEBLE = re.compile(r"(inmueble|alquiler|locaci[oó]n\s+(?:de|del)\s+(?:un|uno|dos|\(|inmueble|local|edificio)|en\s+locaci[oó]n|comodato|"
                         r"sede\b[^.]{0,80}(?:traslad|mudanz)|obra|remodelaci|refacci|puesta en valor|mudanza)", re.I)
RX_INGRESO = re.compile(r"^(Design\w*|Autoriz\w*\s+(?:la|las)\s+contrataci\w*|Contrat\w*|Incorpor\w*)\b", re.I)
RX_TAREAS = re.compile(r"(desempe[ñn]ar\s+tareas|prestar\s+servicios|cumplir\s+funciones|agrupamiento|tramo|como\s+profesional)", re.I)
RX_TRASLADO = re.compile(r"^Traslad\w*", re.I)
RX_EGRESO = re.compile(r"^(Rescind\w*|Dar\s+por\s+rescindid|Di[oó]\s+por\s+rescindid|Acept\w*[^.]{0,80}(?:renuncia|retiro\s+voluntario)|"
                       r"Dispon\w*\s+la\s+baja|Dio\s+de\s+baja|Dar\s+de\s+baja|Declar\w*\s+la\s+cesant|Limit\w*\s+la\s+(?:designaci|contrataci))", re.I)
RX_CARGO = re.compile(r"funciones\s+de\s+(?:titular|jefe|jefa|coordinador|referente|director)|con\s+funciones\s+de", re.I)
RX_DIRECCION = re.compile(r"(?:sit[oa]s?|ubicad[oa]s?)\s+en\s+(?:la\s+)?(?:calle\s+|avenida\s+|Av\.\s*|ruta\s+)?"
                          r"([^,;]{3,70}?(?:N[°º]\s*)?\d{1,5}[^,;]{0,25}?)(?=,|;|\s+de\s+la\s+(?:localidad|ciudad)|\s+esquina|$)", re.I)
RX_FECHA = re.compile(r"^(\d\d)-(\d\d)-(\d\d)$")


def dependencia(txt):
    for m in RX_DEP.finditer(txt):
        nombre = m.group(2).strip(" -–")
        nombre = re.sub(r"\s+(?:de\s+la|del|de)$", "", nombre).strip()
        if clave_lugar(nombre) in {clave_lugar(g) for g in GENERICOS} or len(nombre) < 2:
            continue
        t = m.group(1).lower()
        tipo = "Boca de Atención" if t.startswith("boca") else "Agencia" if t.startswith(("agencia", "udai")) else "CAP"
        return nombre, tipo
    return None, None


def persona(txt):
    if re.search(r"(personas|agentes|trabajadores)\s+(nominad|detallad|que\s+se\s+detallan|consignad|mencionad)", txt, re.I):
        return None
    m = RX_PERSONA.search(txt)
    if not m:
        return None
    p = nombre_propio(m.group(1).strip(" ,."))
    return p if 2 <= len(p.split()) <= 7 else None


def direccion(txt):
    m = RX_DIRECCION.search(txt)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def fecha(boletin, anio):
    m = RX_FECHA.match(boletin or "")
    return f"20{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else f"{anio}-01-01"


def clasificar(txt):
    if RX_ESTRUCTURA.search(txt) and re.search(r"Agencia|Centro de Atenci|CAP\b|Boca|Unidad de Gesti|UGL|Coordinaci|Departamento|Divisi|Direcci[oó]n Adjunta|Sector|Equipo", txt):
        return "estructura"
    if RX_CARGO.search(txt):
        return None                                   # cargos: ya los procesa procesar_boletines.py
    if RX_EGRESO.search(txt):
        return "personal"
    if RX_TRASLADO.search(txt) and persona(txt):
        return "personal"
    if RX_INGRESO.search(txt) and RX_TAREAS.search(txt):
        return "personal"
    if RX_INMUEBLE.search(txt):
        return "inmuebles"
    return None


def main():
    with open(ENTRADA, encoding="utf-8") as f:
        normas = json.load(f)["normas"]
    ugls, sin_ugl, vistos = {}, 0, set()
    for anio, cat, nro, boletin, texto in normas:
        txt = RX_ID.sub("", texto).strip()
        txt = re.sub(r"\bIa\b", "la", txt)                       # OCR: 'Ia' por 'la'
        txt = re.sub(r"\s*\((?:CAP|C\.A\.P\.)\)", "", txt)
        if re.match(r"^Cre\w*\s+(?:los|el)\s+Fondos?", txt, re.I):
            continue
        tipo = clasificar(txt)
        if not tipo:
            continue
        norma = f"{'DI' if cat == 'D' else 'RESOL'}-{anio}-{nro}"
        if (norma, tipo) in vistos:
            continue
        vistos.add((norma, tipo))
        ugl = detectar_ugl(txt)
        if not ugl:
            sin_ugl += 1
            continue
        dep, tipo_dep = dependencia(txt)
        item = {"fecha": fecha(boletin, anio), "norma": norma, "texto": txt[:400]}
        if dep:
            item.update({"dep": dep, "tipo_dep": tipo_dep})
        if tipo == "estructura":
            v = txt.lower()
            dep_ini = re.match(r"^(?:cre\w*|supri\w*|desafect\w*)\s+(?:la|el)\s+(agencia|boca de atenci|centro de atenci|cap\b)", v)
            item["accion"] = ("crea" if dep_ini and v.startswith("cre") else "suprime" if dep_ini else
                              "renombra" if "denominaci" in v[:80] else "modifica")
            # 'Creó la Boca de Atención Alberdi y la Boca de Atención Banda Norte': un ítem por dependencia
            deps = [(m.group(2).strip(), m.group(1)) for m in RX_DEP.finditer(txt)]
            if item["accion"] in ("crea", "suprime") and len(deps) > 1 and re.search(r"\sy\s+(?:la|el)\s+(?:Agencia|Boca|Centro|CAP)", txt[:200]):
                deps = [d for d in deps if txt.find(d[0]) < (re.search(r"desafect|supri", txt, re.I) or re.search(r"$", txt)).start()]
                for nombre, t in deps:
                    if clave_lugar(nombre) in {clave_lugar(g) for g in GENERICOS}:
                        continue
                    tt = "Boca de Atención" if t.lower().startswith("boca") else "Agencia" if t.lower().startswith(("agencia", "udai")) else "CAP"
                    ugls.setdefault(ugl, {"estructura": [], "inmuebles": [], "personal": []})["estructura"].append(
                        dict(item, dep=nombre, tipo_dep=tt))
                continue
        elif tipo == "inmuebles":
            d = direccion(txt)
            if d:
                item["direccion"] = d
            v = txt.lower()
            item["accion"] = ("obra" if re.search(r"obra|remodelaci|refacci|puesta en valor", v) else
                              "busqueda" if re.search(r"b[uú]squeda|llamado|apto para|concurso|compulsa", v) else
                              "renovacion" if "renov" in v else "alquiler")
        else:
            p = persona(txt)
            if not p:
                continue
            item["persona"] = p
            item["accion"] = ("egreso" if RX_EGRESO.search(txt) else "traslado" if RX_TRASLADO.search(txt) else "ingreso")
        ugls.setdefault(ugl, {"estructura": [], "inmuebles": [], "personal": []})[tipo].append(item)

    for u in ugls.values():
        for k in u:
            u[k].sort(key=lambda x: x["fecha"], reverse=True)
    tot = {k: sum(len(u[k]) for u in ugls.values()) for k in ("estructura", "inmuebles", "personal")}
    salida = {"_nota": "Generado por procesar_catalogo.py desde catalogo_pami.json (buscador de www.pami.org.ar/boletin-oficial).",
              "_totales": tot, "ugls": dict(sorted(ugls.items()))}
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"[OK] datos_extra.json · estructura {tot['estructura']} · inmuebles {tot['inmuebles']} · personal {tot['personal']} · {sin_ugl} sin UGL")


if __name__ == "__main__":
    main()
