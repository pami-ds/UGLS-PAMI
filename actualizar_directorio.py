"""
Actualiza directorio_agencias.json (domicilios, teléfonos, altas y bajas) con el buscador oficial
www.pami.org.ar/agencias-ugls.

  python actualizar_directorio.py            descarga el buscador (necesita acceso a pami.org.ar) y actualiza
  python actualizar_directorio.py --local    usa el directorio_web.json ya descargado

Reglas:
  - si el domicilio cambió de verdad (otra calle u otra altura) se reemplaza y se guarda el anterior en
    "domicilio_anterior"; las diferencias de escritura ("Av." / "Avenida", acentos) no cuentan como cambio;
  - se agregan las agencias, CAPs, bocas y postas nuevas ("nuevo_web": true);
  - las que ya no figuran en el buscador quedan marcadas con "no_figura_web": true (no se borran).
"""
import datetime
import json
import os
import re
import sys
import unicodedata

BASE = os.path.dirname(os.path.abspath(__file__))
DIRECTORIO = os.path.join(BASE, "directorio_agencias.json")
WEB = os.path.join(BASE, "directorio_web.json")
URL = "https://www.pami.org.ar/UglsAgencias/seleccionarServicio"

STOP = {"AV", "AVENIDA", "CALLE", "E", "Y", "ENTRE", "ESQ", "ESQUINA", "PTE", "PRESIDENTE", "GRAL", "GENERAL", "N", "SN", "S",
        "DE", "DEL", "LA", "EL", "LOS", "LAS", "PB", "LOCAL", "TTE", "TENIENTE", "DR", "DOCTOR", "ING", "INGENIERO", "BIS", "MZ",
        "JUAN", "JOSE", "M", "MARIA", "B", "BAUTISTA", "DOMINGO"}
CONECTORES = {"de", "del", "la", "las", "los", "y", "e", "el"}


def sin_tildes(s):
    return unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().upper()


def tokens(s):
    w = re.findall(r"[A-Z]+|\d+", sin_tildes(s).replace(".", " ").replace("/", " "))
    return {x for x in w if x not in STOP and not x.isdigit()}, {x for x in w if x.isdigit() and x != "0"}


def mismo_domicilio(a, b):
    ta, na = tokens(a)
    tb, nb = tokens(b)
    if na and nb and not (na & nb):
        return False
    if not ta or not tb:
        return bool(na & nb)
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def lindo(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    out = []
    for i, w in enumerate(s.split(" ")):
        lw = w.lower()
        if i and lw in CONECTORES:
            out.append(lw)
        elif re.fullmatch(r"[IVXL]+", w) or w in ("S/N", "PB"):
            out.append(w)
        else:
            out.append(lw[:1].upper() + lw[1:])
    return " ".join(out).replace(" 0", "") if s else ""


def tipo(nombre):
    n = sin_tildes(nombre)
    return "ugl" if n.startswith("UGL") else "boca" if n.startswith(("BOCA", "POSTA")) else "cap" if n.startswith(("CAP", "C.A.P")) else "agencia"


def descargar():
    import requests
    s = requests.Session()
    s.headers.update({"X-Requested-With": "XMLHttpRequest", "User-Agent": "Mozilla/5.0 (graffo PAMI)"})
    srv = lambda **d: s.post(URL, data=d, timeout=60).json()
    ugls = {}
    for p in srv(servicio="BPP_traer_provincias"):
        for u in srv(codigo_provincia=p["C_PROVINCIA_PAMI"], servicio="BPP_traer_UGLs"):
            ugls[u["C_UGL"]] = u
    filas = []
    for cu, u in ugls.items():
        i = (srv(cod_ugl=cu, servicio="BPP_traer_info_UGL") or [{}])[0]
        tel = lambda x: f"({x.get('N_PREFIJO')}) {x.get('N_TELEFONO')}" if x.get("N_TELEFONO") else ""
        filas.append(["ugl", cu, "0000", u["D_AGENCIA"], i.get("DESCRIPCION_LOCALIDAD", ""),
                      f"{i.get('D_CALLE', '')} {i.get('N_PUERTA', '')}".strip(), tel(i), i.get("C_CP8", "")])
        for a in srv(cod_ugl=cu, servicio="BPP_traer_agencias"):
            x = (srv(cod_agencia=a["C_AGENCIA"], cod_ugl=cu, servicio="BPP_traer_info_agencia") or [{}])[0]
            filas.append(["ag", cu, a["C_AGENCIA"], a["D_AGENCIA"], x.get("DESCRIPCION_LOCALIDAD", ""),
                          f"{x.get('D_CALLE', '')} {x.get('N_PUERTA', '')}".strip(), tel(x), x.get("C_CP8", "")])
        print(f"[INFO] UGL {cu}: {len(filas)} filas acumuladas")
    with open(WEB, "w", encoding="utf-8") as f:
        json.dump({"_nota": "Buscador oficial www.pami.org.ar/agencias-ugls. Formato: [tipo, cod_ugl, cod_agencia, nombre, localidad, domicilio, telefono, cp].",
                   "fecha": datetime.date.today().isoformat(), "filas": filas}, f, ensure_ascii=False)
    return filas


def aplicar(filas):
    with open(DIRECTORIO, encoding="utf-8") as f:
        d = json.load(f)
    romano = {e["codigo"][:-4]: k for k, l in d.items() for e in l if e["tipo"] == "ugl"}
    idx = {e["codigo"]: e for l in d.values() for e in l}
    vistos, cambios, nuevos = set(), [], []
    for _, ugl, cod, nom, loc, dom, tel, cp in filas:
        c = str(int(ugl)) + cod
        vistos.add(c)
        tel = tel if tel and re.sub(r"\D", "", tel).strip("0") else ""
        if c in idx:
            e = idx[c]
            if dom and not mismo_domicilio(e["domicilio"], dom):
                cambios.append((e["nombre"], e["domicilio"], lindo(dom)))
                e["domicilio_anterior"], e["domicilio"], e["lat"], e["lon"] = e["domicilio"], lindo(dom), None, None
            if tel:
                e["telefono"] = tel
            if cp:
                e["cp"] = cp
            e.pop("no_figura_web", None)
        else:
            k = romano.get(str(int(ugl)))
            if not k:
                continue
            e = {"codigo": c, "nombre": nom, "tipo": tipo(nom), "domicilio": lindo(dom),
                 "localidad": lindo(loc) if loc and "DESCONOC" not in loc.upper() else "", "lat": None, "lon": None, "nuevo_web": True}
            if tel:
                e["telefono"] = tel
            d[k].append(e)
            idx[c] = e
            nuevos.append(nom)
    bajas = [e["nombre"] for c, e in idx.items() if c not in vistos]
    for c, e in idx.items():
        if c not in vistos:
            e["no_figura_web"] = True
    with open(DIRECTORIO, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"[OK] {len(cambios)} domicilios cambiados · {len(nuevos)} nuevas · {len(bajas)} ya no figuran")
    for c in cambios:
        print("   ", c)


if __name__ == "__main__":
    if "--local" in sys.argv:
        with open(WEB, encoding="utf-8") as f:
            filas = json.load(f)["filas"]
    else:
        filas = descargar()
    aplicar(filas)
