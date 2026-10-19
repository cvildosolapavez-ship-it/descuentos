#!/usr/bin/env python3
"""
Scraper de descuentos bancarios en Chile -> descuentos.json

Lo ejecuta GitHub Actions todos los días (ver .github/workflows/actualizar.yml).
También puedes correrlo en tu computador:

    pip install -r requirements.txt
    playwright install chromium
    python scraper.py                       # todos los bancos
    python scraper.py --bancos bchile bci   # solo algunos
    python scraper.py --demo                # prueba el lector con HTML de ejemplo

Cómo protege tus datos:
- Los descuentos con "origen": "manual" (los que cargas a mano) nunca se borran.
- Si un banco devuelve 0 resultados (sitio caído o cambió su diseño),
  se conservan los descuentos que ya tenía de ese banco.

Si un banco devuelve 0 resultados por varios días, su página cambió:
abre su sitio de beneficios, inspecciona una tarjeta de descuento y
ajusta "url" y "selector" en BANCOS.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Tag

log = logging.getLogger("descuentos")

CHILE = timezone(timedelta(hours=-3))
DELAY_S = 2.0
TIMEOUT_S = 30
HEADERS = {
    "User-Agent": "DescuentosDelDia/1.0 (proyecto personal)",
    "Accept-Language": "es-CL,es;q=0.9",
}

# --------------------------------------------------------------------------
# Configuración por banco. VERIFICAR: las URLs y el diseño cambian seguido.
#   url      : página pública de beneficios
#   js       : True si el listado se carga con JavaScript (usa Playwright)
#   selector : CSS de cada tarjeta de descuento. None = detección automática
#   titulo   : CSS del nombre del comercio dentro de la tarjeta (opcional)
# --------------------------------------------------------------------------
BANCOS: dict[str, dict] = {
    "bchile":    {"nombre": "Banco de Chile",  "url": "https://sitiospublicos.bancochile.cl/personas/beneficios", "js": True,  "selector": None, "titulo": None},
    "estado":    {"nombre": "BancoEstado",     "url": "https://www.bancoestado.cl/beneficios",                    "js": True,  "selector": None, "titulo": None},
    "santander": {"nombre": "Santander",       "url": "https://banco.santander.cl/beneficios",                    "js": True,  "selector": None, "titulo": None},
    "bci":       {"nombre": "BCI",             "url": "https://www.bci.cl/beneficios/beneficios-bci",             "js": True,  "selector": None, "titulo": None},
    "scotia":    {"nombre": "Scotiabank",      "url": "https://www.scotiabankchile.cl/beneficios",                "js": True,  "selector": None, "titulo": None},
    "itau":      {"nombre": "Itaú",            "url": "https://itaubeneficios.cl",                                "js": True,  "selector": None, "titulo": None},
    "falabella": {"nombre": "Banco Falabella", "url": "https://www.bancofalabella.cl/descuentos",                 "js": True,  "selector": None, "titulo": None},
    "security":  {"nombre": "Security",        "url": "https://www.bancosecurity.cl/beneficios",                  "js": True,  "selector": None, "titulo": None},
    "ripley":    {"nombre": "Banco Ripley",    "url": "https://www.bancoripley.cl/beneficios",                    "js": True,  "selector": None, "titulo": None},
}

CATEGORIAS: dict[str, list[str]] = {
    "bencina":         ["copec", "shell", "petrobras", "aramco", "bencina", "combustible", "litro"],
    "supermercado":    ["jumbo", "lider", "tottus", "unimarc", "santa isabel", "acuenta", "supermercado"],
    "salud":           ["cruz verde", "salcobrand", "ahumada", "farmacia", "clinica", "dental", "optica"],
    "belleza":         ["preunic", "sephora", "dbs", "peluqueria", "spa", "manicure", "barberia", "cosmetic", "belleza"],
    "moda":            ["paris", "h&m", "zara", "adidas", "nike", "vestuario", "calzado", "ropa", "moda"],
    "viajes":          ["sky", "latam", "jetsmart", "hotel", "turismo", "viaje", "vuelo", "despegar"],
    "entretenimiento": ["cinemark", "cineplanet", "cinepolis", "cine", "teatro", "concierto", "fantasilandia",
                        "puntoticket", "ticketmaster", "museo", "parque", "bowling", "entretencion"],
    "comida":          ["restaurant", "restoran", "sushi", "pizza", "burger", "cafe", "starbucks", "juan maestro",
                        "mamut", "domino", "papa john", "mcdonald", "kfc", "delivery", "rappi", "pedidosya",
                        "comida", "gastronomia", "bar", "sabores"],
}

DIAS = {"domingo": 0, "lunes": 1, "martes": 2, "miercoles": 3, "jueves": 4, "viernes": 5, "sabado": 6}


@dataclass
class Descuento:
    shop: str
    cat: str
    bank: str
    pct: int
    days: list[int]
    cond: str
    perLitre: bool = False
    upTo: bool = False
    loc: str = ""
    vig: str = ""
    url: str = ""
    origen: str = "scraper"
    leido: str = field(default_factory=lambda: datetime.now(CHILE).date().isoformat())


# ------------------------------- texto ------------------------------------
def normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def limpiar(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


RE_PCT = re.compile(r"(\d{1,3})\s?%")
RE_HASTA = re.compile(r"hasta\s+(?:un\s+)?\d{1,3}\s?%", re.I)
RE_LITRO = re.compile(r"\$\s?(\d{2,4})\s*(?:de\s+)?(?:dcto\.?|descuento)?\s*(?:por|x|/)\s*litro", re.I)
RE_RANGO = re.compile(r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+a\s+(lunes|martes|miercoles|jueves|viernes|sabado|domingo)")
RE_VIG = re.compile(r"(?:hasta|vigente hasta|valido hasta|al)\s+(?:el\s+)?(\d{1,2}\s+de\s+[a-z]+(?:\s+de\s+\d{4})?)", re.I)


def parse_dias(texto: str) -> list[int]:
    t = normalizar(texto)
    if re.search(r"todos los dias|todo el mes|lunes a domingo|7 dias", t):
        return list(range(7))
    dias: set[int] = set()
    for a, b in RE_RANGO.findall(t):
        i, j = DIAS[a], DIAS[b]
        dias.update(range(i, j + 1) if i <= j else [*range(i, 7), *range(0, j + 1)])
    if "fin de semana" in t or "fines de semana" in t:
        dias.update({0, 6})
    for nombre, n in DIAS.items():
        if re.search(rf"\b{nombre}s?\b", t):
            dias.add(n)
    return sorted(dias)


def parse_pct(texto: str) -> tuple[int | None, bool]:
    m = RE_LITRO.search(texto)
    if m:
        return int(m.group(1)), True
    vals = [int(v) for v in RE_PCT.findall(texto) if 1 <= int(v) <= 100]
    return (max(vals), False) if vals else (None, False)


def clasificar(texto: str) -> str:
    t = normalizar(texto)
    for cat, claves in CATEGORIAS.items():
        if any(re.search(rf"\b{re.escape(k)}", t) for k in claves):
            return cat
    return "otros"


def corto(texto: str, limite: int = 160) -> str:
    texto = limpiar(texto)
    return texto if len(texto) <= limite else texto[: limite - 1].rsplit(" ", 1)[0] + "…"


# ------------------------------ descarga ----------------------------------
def bajar_html(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.text


def bajar_html_js(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright no está instalado; uso descarga simple para %s", url)
        return bajar_html(url)
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pag = nav.new_page(user_agent=HEADERS["User-Agent"], locale="es-CL")
        pag.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_S * 1000)
        try:
            pag.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        for _ in range(10):  # bajar para cargar listados perezosos
            pag.mouse.wheel(0, 2500)
            pag.wait_for_timeout(700)
        html = pag.content()
        nav.close()
    return html


# ------------------------------ extracción --------------------------------
def tarjetas_auto(soup: BeautifulSoup) -> list[Tag]:
    """Bloques pequeños que mencionan un % o $/litro."""
    cand = [el for el in soup.find_all(["article", "li", "div", "a", "section"])
            if 20 <= len(el.get_text(" ", strip=True)) <= 400
            and (RE_PCT.search(el.get_text(" ")) or RE_LITRO.search(el.get_text(" ")))]
    ids = {id(c) for c in cand}
    return [c for c in cand if not any(id(d) in ids for d in c.find_all(True))]


def nombre_comercio(card: Tag, sel: str | None) -> str:
    if sel and (t := card.select_one(sel)):
        return limpiar(t.get_text(" "))[:60]
    for tag in ("h2", "h3", "h4", "h5", "strong", "b"):
        t = card.find(tag)
        if t and not RE_PCT.search(t.get_text()):
            return limpiar(t.get_text(" "))[:60]
    img = card.find("img", alt=True)
    if img and img["alt"].strip():
        return limpiar(img["alt"])[:60]
    primera = limpiar(card.get_text("\n").split("\n")[0])
    return RE_PCT.sub("", primera).strip(" -–:")[:60] or "Comercio"


def extraer(html: str, banco: str, cfg: dict) -> list[Descuento]:
    soup = BeautifulSoup(html, "lxml")
    for b in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        b.decompose()
    cards = soup.select(cfg["selector"]) if cfg.get("selector") else tarjetas_auto(soup)
    out: list[Descuento] = []
    for c in cards:
        texto = limpiar(c.get_text(" "))
        pct, litro = parse_pct(texto)
        if pct is None:
            continue
        shop = nombre_comercio(c, cfg.get("titulo"))
        a = c if c.name == "a" else c.find("a", href=True)
        link = urljoin(cfg["url"], a["href"]) if a and a.get("href") else cfg["url"]
        vig = RE_VIG.search(normalizar(texto))
        out.append(Descuento(
            shop=shop, cat=clasificar(f"{shop} {texto}"), bank=banco, pct=pct,
            days=parse_dias(texto) or list(range(7)),
            cond=corto(texto.replace(shop, "", 1)),
            perLitre=litro, upTo=bool(RE_HASTA.search(texto)),
            vig=f"Hasta {vig.group(1)}" if vig else "",
            url=link,
        ))
    return out


# ------------------------------ mezcla ------------------------------------
def clave(d: dict) -> tuple:
    return (d["bank"], normalizar(d["shop"]), d["pct"], tuple(d["days"]))


def mezclar(previos: list[dict], nuevos: dict[str, list[Descuento]]) -> list[dict]:
    manuales = [d for d in previos if d.get("origen") == "manual"]
    vistos = {clave(d) for d in manuales}
    resultado = list(manuales)
    for banco in BANCOS:
        if nuevos.get(banco):
            lista = [asdict(d) for d in nuevos[banco]]
        else:  # sin resultados: conservar lo anterior de ese banco
            lista = [d for d in previos if d.get("origen") != "manual" and d["bank"] == banco]
        for d in lista:
            if clave(d) not in vistos:
                vistos.add(clave(d))
                resultado.append(d)
    for i, d in enumerate(resultado):
        d["id"] = i
    return resultado


def scrapear(bancos: list[str]) -> dict[str, list[Descuento]]:
    res: dict[str, list[Descuento]] = {}
    for i, b in enumerate(bancos):
        cfg = BANCOS[b]
        if i:
            time.sleep(DELAY_S)
        try:
            html = bajar_html_js(cfg["url"]) if cfg["js"] else bajar_html(cfg["url"])
            res[b] = extraer(html, b, cfg)
            log.info("%-16s %3d descuentos", cfg["nombre"], len(res[b]))
            if not res[b]:
                log.warning("  0 resultados en %s: se conservan los anteriores", cfg["url"])
        except Exception as e:  # un banco caído no detiene a los demás
            log.error("%-16s error: %s (se conservan los anteriores)", cfg["nombre"], e)
    return res


DEMO_HTML = """
<div class="grid">
  <article><h3>Cinemark</h3><p>40% dcto. en entradas 2D/3D todos los miércoles. Vigente hasta 31 de octubre.</p></article>
  <article><h3>Sushi Osaka</h3><p>Hasta 35% de descuento viernes y sábado. Tope $15.000.</p></article>
  <article><h3>Copec</h3><p>$100 de dcto. por litro los viernes pagando con app.</p></article>
  <article><h3>Preunic</h3><p>20% en cuidado personal de lunes a jueves.</p></article>
</div>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Scraper de descuentos bancarios en Chile")
    ap.add_argument("--bancos", nargs="+", choices=list(BANCOS), default=list(BANCOS))
    ap.add_argument("--out", default="descuentos.json")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if a.demo:
        for d in extraer(DEMO_HTML, "bchile", BANCOS["bchile"]):
            print(d.shop, d.cat, d.pct, "hasta" if d.upTo else "", d.days, d.vig)
        return 0

    previos: list[dict] = []
    if os.path.exists(a.out):
        with open(a.out, encoding="utf-8") as f:
            j = json.load(f)
            previos = j["descuentos"] if isinstance(j, dict) else j

    datos = mezclar(previos, scrapear(a.bancos))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"actualizado": datetime.now(CHILE).isoformat(timespec="minutes"),
                   "descuentos": datos}, f, ensure_ascii=False, indent=2)
    log.info("Guardado %s: %d descuentos (%d manuales)", a.out, len(datos),
             sum(d.get("origen") == "manual" for d in datos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
