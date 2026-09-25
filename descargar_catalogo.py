"""
Descarga del buscador de www.pami.org.ar/boletin-oficial los resúmenes de todas las normas
(resoluciones y disposiciones) que mencionan UGLs, agencias, CAPs o bocas, y los guarda en
catalogo_pami.json. Después corré  python procesar_catalogo.py  para regenerar datos_extra.json.

Uso:  python descargar_catalogo.py [DESDE] [HASTA]      (por defecto 2016 hasta el año actual)
"""
import datetime
import html
import json
import os
import re
import sys
import time

import requests

URL = "https://www.pami.org.ar/listado-resoluciones"
BASE = os.path.dirname(os.path.abspath(__file__))
SALIDA = os.path.join(BASE, "catalogo_pami.json")
CATEGORIAS = {"1": "R", "5": "D"}          # 1 = Resolución, 5 = Disposición
RX_LUGAR = re.compile(r"(Unidad de Gesti[oó]n Local|\bUGL|Agencia|Centro de Atenci[oó]n Personalizad|\bCAP\b|Boca de Atenci)", re.I)


def texto_plano(h):
    t = re.sub(r"<[^>]+>", " ", h or "")
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"\s*EX-\d{4}-\d+.*$", "", t)


def consultar(anio, categoria):
    datos = {"detalle": "", "nro": "", "anio": str(anio), "categoria": categoria, "nro_expediente": ""}
    for intento in range(3):
        try:
            r = requests.post(URL, data=datos, timeout=60, headers={"X-Requested-With": "XMLHttpRequest",
                                                                     "User-Agent": "Mozilla/5.0 (graffo PAMI)"})
            r.raise_for_status()
            return r.json()
        except Exception as ex:
            print(f"[AVISO] {anio}/{categoria}: {ex} (reintento {intento + 1})")
            time.sleep(5)
    return []


def main():
    hoy = datetime.date.today().year
    desde = int(sys.argv[1]) if len(sys.argv) > 1 else 2016
    hasta = int(sys.argv[2]) if len(sys.argv) > 2 else hoy
    filas = []
    for anio in range(desde, hasta + 1):
        for cat, letra in CATEGORIAS.items():
            res = consultar(anio, cat)
            n = 0
            for x in res:
                t = texto_plano(x.get("detalle"))
                if not RX_LUGAR.search(t):
                    continue
                try:
                    nro = int(x.get("nro"))
                except (TypeError, ValueError):
                    continue
                filas.append([str(x.get("anio") or anio), letra, nro, (x.get("link_doc") or "").replace(".pdf", ""), t[:420]])
                n += 1
            print(f"[INFO] {anio} {letra}: {len(res)} normas, {n} con UGL/agencia")
    # si ya había un catálogo, se conservan los años no descargados ahora
    if os.path.exists(SALIDA):
        with open(SALIDA, encoding="utf-8") as f:
            viejas = [r for r in json.load(f).get("normas", []) if not desde <= int(r[0]) <= hasta]
        filas = viejas + filas
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({"_nota": "Resúmenes del buscador de www.pami.org.ar/boletin-oficial que mencionan UGLs, agencias, CAPs o bocas. "
                            "Formato: [año, R/D, número, boletín, resumen].", "normas": filas},
                  f, ensure_ascii=False, separators=(",", ":"))
    print(f"[OK] catalogo_pami.json · {len(filas)} normas")


if __name__ == "__main__":
    main()
