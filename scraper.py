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
    # Banco de Chile publica sus beneficios en una API interna (se lee desde el navegador).
    "bchile":    {"nombre": "Banco de Chile",  "api": "bchile",
                  "url": "https://sitiospublicos.bancochile.cl/personas/beneficios"},
    # BancoEstado, Santander e Itaú bloquean navegadores automáticos: se respetan
    # y se mantienen solo los descuentos cargados a mano.
    "estado":    {"nombre": "BancoEstado",     "activo": False, "url": "https://www.bancoestado.cl/beneficios"},
    "santander": {"nombre": "Santander",       "activo": False, "url": "https://banco.santander.cl/beneficios"},
    "itau":      {"nombre": "Itaú",            "activo": False, "url": "https://itaubeneficios.cl"},
    "bci":       {"nombre": "BCI",             "url": "https://www.bci.cl/beneficios/beneficios-bci", "js": True,
                  "selector": None, "titulo": None},
    "scotia":    {"nombre": "Scotiabank",      "url": "https://www.scotiabankchile.cl/beneficios", "js": True,
                  "selector": ".scotia-box-solid, .sc-box-bannerhero", "titulo": None},
    "falabella": {"nombre": "Banco Falabella", "url": "https://www.bancofalabella.cl/descuentos", "js": True,
                  "selector": 'div[class*="NewCardBenefits_content"]', "titulo": '[class*="NewCardBenefits_title"]'},
    "security":  {"nombre": "Security",        "js": True, "selector": None, "titulo": None,
                  "urls": ["https://personas.bancosecurity.cl/beneficios",
                           "https://personas.bancosecurity.cl/beneficios/gourmet"]},
    "ripley":    {"nombre": "Banco Ripley",    "url": "https://www.bancoripley.cl/beneficios-y-promociones", "js": True,
                  "selector": None, "titulo": None},
}

# El orden importa: gana la primera categoría que coincida.
# Cada palabra se busca completa (con plural opcional), así "bar" no calza con "barato".
CATEGORIAS: dict[str, list[str]] = {
    "bencina":         ["copec", "shell", "petrobras", "aramco", "bencina", "combustible", "litro"],
    "entretenimiento": ["cinemark", "cineplanet", "cinepolis", "cine", "teatro", "concierto", "fantasilandia",
                        "puntoticket", "ticketmaster", "museo", "parque", "bowling", "entretencion",
                        "chuck e. cheese", "chuck e cheese", "kidzania", "buin zoo", "show", "evento", "color run",
                        "carrera", "running", "festival", "entrada"],
    "comida":          ["restaurant", "restaurante", "restoran", "sushi", "pizza", "pizzeria", "burger", "hamburguesa",
                        "cafe", "cafeteria", "starbucks", "juan maestro", "mamut", "domino", "papa john", "papa johns",
                        "mcdonald", "mcdonalds", "mccombo", "kfc", "delivery", "rappi", "pedidosya", "uber eats",
                        "comida", "cocina", "gastronomia", "gourmet", "bar", "sabores", "dunkin", "doggis",
                        "tommy beans", "chicken", "chick'en", "latte", "le vice", "lovdo", "wendy", "china wok",
                        "telepizza", "pizza hut", "kitchen", "sandwich", "sangucheria", "heladeria", "pasteleria",
                        "panaderia", "nikkei", "mexicana", "peruana", "parrilla", "grill", "brunch", "almuerzo",
                        "caffe", "coffee", "churro", "churromania", "pretzel", "paleta", "palettas", "helado",
                        "emporio", "dulce", "dulcentorno", "jugo", "boost", "shawarma", "wrap", "taco", "empanada"],
    "supermercado":    ["jumbo", "lider", "tottus", "unimarc", "santa isabel", "acuenta", "supermercado", "mercado"],
    "salud":           ["cruz verde", "salcobrand", "ahumada", "farmacia", "clinica", "dental", "optica",
                        "nutrition", "suplemento", "medico", "laboratorio"],
    "belleza":         ["preunic", "sephora", "dbs", "peluqueria", "spa", "manicure", "barberia", "cosmetica",
                        "belleza", "piel", "okami", "maquillaje", "perfumeria", "skincare"],
    "moda":            ["paris", "h&m", "zara", "adidas", "nike", "vestuario", "calzado", "ropa", "moda",
                        "zapatilla", "zapato"],
    "viajes":          ["sky", "latam", "jetsmart", "hotel", "turismo", "viaje", "vuelo", "despegar",
                        "avis", "budget", "arriendo de auto", "arrendar un auto", "rent a car", "cabify", "uber",
                        "estacionamiento", "aeropuerto"],
}

# Textos que no son descuentos en comercios: productos financieros del banco.
RE_NO_ES_DESCUENTO = re.compile(
    r"\btasa\b|credito de consumo|hipotecari|\binvert|\binversion|fogape|seguro de (?:auto|vida|hogar|salud)"
    r"|abre (?:hoy )?(?:tu |una )?cuenta|portabilidad|pago automatico de cuentas|refinancia",
)
# Ofertas de productos en tienda (ej. "$25.990 -46% $47.990"), no beneficios por día.
RE_PRECIO_PRODUCTO = re.compile(r"-\d{1,2}\s?%.*\$\s?\d|\$\s?\d[\d.]*\s*-\d{1,2}\s?%")

# Nombres que no identifican un comercio (días, etiquetas genéricas, títulos de promoción).
RE_NOMBRE_GENERICO = re.compile(
    r"^(?:nuevo|nueva|hasta|comercio|restaurante|restaurantes|tienda|tiendas|cmr|dcto\.?|descuento|beneficio|ver mas|ver detalle|mañana|manana|hoy|todos los dias"
    r"|(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|lu|ma|mi|ju|vi|sa|do)"
    r"(?:\s*(?:,|y|a|-)\s*(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|lu|ma|mi|ju|vi|sa|do))*)$"
)

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


RE_PCT = re.compile(r"(?<![\d,.])(\d{1,3})\s?%(?!\s*(?:online|digital|gratis|garantizad|financiad))", re.I)
RE_HASTA = re.compile(r"hasta\s+(?:un\s+)?\d{1,3}\s?%", re.I)
RE_LITRO = re.compile(r"\$\s?(\d{2,4})\s*(?:de\s+)?(?:dcto\.?|descuento)?\s*(?:por|x|/)\s*litro", re.I)
RE_RANGO = re.compile(r"(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+a\s+(lunes|martes|miercoles|jueves|viernes|sabado|domingo)")
RE_VIG = re.compile(r"(?:hasta|vigente hasta|valido hasta|al)\s+(?:el\s+)?(\d{1,2}\s+de\s+[a-z]+(?:\s+de\s+\d{4})?)", re.I)


ABREV = {"do": 0, "lu": 1, "ma": 2, "mi": 3, "ju": 4, "vi": 5, "sa": 6}
RE_ABREV = re.compile(r"\b(?:lu|ma|mi|ju|vi|sa|do)(?:\s?-\s?(?:lu|ma|mi|ju|vi|sa|do))+\b")


def hoy_idx() -> int:
    """Día de hoy en Chile, con 0 = domingo."""
    return (datetime.now(CHILE).weekday() + 1) % 7


def parse_dias(texto: str) -> list[int]:
    t = normalizar(texto)
    if re.search(r"todos los dias|todo el mes|lunes a domingo|7 dias", t):
        return list(range(7))
    dias: set[int] = set()
    for grupo in RE_ABREV.findall(t):  # "Sá-Do-Lu", "Vi-Sá-Do-Lu-Mi"
        dias.update(ABREV[a] for a in re.split(r"\s?-\s?", grupo))
    # Algunos sitios muestran "Hoy" / "Mañana" en vez del día de la semana
    if re.search(r"\bhoy\b", t):
        dias.add(hoy_idx())
    if re.search(r"\bmanana\b", t):
        dias.add((hoy_idx() + 1) % 7)
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
        if any(re.search(rf"(?<!\w){re.escape(k)}(?:s|es)?(?!\w)", t) for k in claves):
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


RE_PREFIJO = re.compile(r"^(?:(?:dcto\.?|descuento|beneficio)\s+(?:en|de|del)\s+)?(?:la\s+)?(?:app|tienda)\s+(?:de\s+)?|^(?:dcto\.?|descuento|beneficio)\s+(?:en|de|del)\s+", re.I)
RE_ANTES_PCT = re.compile(r"^([A-ZÁÉÍÓÚÑ0-9][\w'’&.\- ]{1,40}?)\s+(?:hasta\s+)?\d{1,3}\s?%")
RE_EN_COMERCIO = re.compile(
    r"(?i:dcto\.?|descuento|devoluci[oó]n)\s+(?i:en)\s+([A-ZÁÉÍÓÚÑ][\w'&.]+(?:\s[A-ZÁÉÍÓÚÑ0-9][\w'&.]*){0,3})")
MARCAS = {k: n for n in (
    "Copec", "Shell", "Petrobras", "Aramco", "Starbucks", "McDonald's", "Juan Maestro", "Doggis", "Mamut",
    "Domino's", "Papa John's", "Pizza Hut", "Telepizza", "KFC", "Burger King", "Wendy's", "Dunkin'",
    "PedidosYa", "Rappi", "Uber Eats", "Cinemark", "Cineplanet", "Cinépolis", "Fantasilandia", "Preunic",
    "Sephora", "Cruz Verde", "Salcobrand", "Farmacias Ahumada", "Jumbo", "Lider", "Tottus", "Unimarc",
    "Santa Isabel", "Paris", "Falabella", "Ripley", "Sky Airline", "LATAM", "JetSMART", "Avis",
) for k in [normalizar(n).replace("'", "")]}
IMG_GENERICA = re.compile(r"logo|banner|imagen|image|icono|icon|foto|^\W*$", re.I)


COLA = re.compile(r"(?:\s+(?:exclusivo|presencial|pagando|valido|válido|solo|con|por|en|todos|hasta|sin|y|online|vigente))+$", re.I)


RUIDO_ARCHIVO = {"thumbnail", "thumb", "card", "cards", "bd", "bn", "img", "web", "banner", "beneficio", "beneficios",
                 "logos", "nuevo", "new", "final", "v", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre", "copia", "copy", "sitio"}


def nombre_desde_archivo(src: str) -> str:
    """'Cards_LOGO_Web_Baqueano.webp' -> 'Baqueano'; 'DOMINGA BISTRO LOGO WEB 15' -> 'Dominga Bistro'."""
    base = os.path.splitext(os.path.basename(src.split("?")[0]))[0]
    if re.search(r"icon|calendar|arrow|chevron|sin.?t.?tulo|dise.?o|[^\x00-\x7f]", base, re.I):
        return ""
    base = re.sub(r"\d{4,}", " ", base)
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    tokens = re.split(r"[\s_\-]+", base)
    partes, actual = [], []
    for t in tokens:
        if t.lower() == "logo":
            partes.append(actual); actual = []
        elif t and not t.isdigit() and t.lower() not in RUIDO_ARCHIVO and not re.fullmatch(r"\d+\w{0,2}", t):
            actual.append(t)
    partes.append(actual)
    for parte in reversed(partes):  # el nombre suele ir después de "logo"
        nombre = " ".join(parte)
        if 2 <= len(nombre) <= 30:
            return nombre.title() if nombre.isupper() else nombre
    return ""


def limpiar_nombre(s: str) -> str:
    s = COLA.sub("", RE_PREFIJO.sub("", limpiar(s))).strip(" -–:|·.")
    return s[:1].upper() + s[1:60] if s else ""


def es_generico(nombre: str) -> bool:
    n = normalizar(nombre).strip(" .!¡?")
    if re.fullmatch(r"[\d\s%$.,]+", n) or n.startswith(("en www", "www.")):
        return True
    return (not n or bool(RE_NOMBRE_GENERICO.match(n)) or bool(RE_PCT.search(nombre))
            or n.startswith(("hasta ", "todos los", "disfruta", "canjea", "aprovecha", "conoce", "exclusivo",
                             "presencial", "valido", "sin tope", "pagando", "con tu", "con tus", "solo ",
                             "promocion", "compra", "pide", "usa ", "paga ", "vigencia", "ver ", "dcto")))


def nombre_comercio(card: Tag, sel: str | None, texto: str) -> str | None:
    """Busca el nombre del comercio entre varios candidatos y descarta los genéricos.
    Devuelve None si no encuentra ninguno útil."""
    if sel and (t := card.select_one(sel)):
        n = limpiar_nombre(t.get_text(" "))
        if not es_generico(n):
            return n
    candidatos: list[str] = []

    def textos(tags: list[str]) -> None:
        for tag in card.find_all(tags):
            txt = tag.get_text(" ", strip=True)
            if 2 <= len(txt) <= 50:
                candidatos.append(txt)

    textos(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"])  # 1) títulos
    for img in card.find_all("img"):  # 2) logos con texto alternativo
        for attr in ("alt", "title"):
            v = (img.get(attr) or "").strip()
            if v and not IMG_GENERICA.search(v):
                candidatos.append(v)
    for img in card.find_all("img", src=True):  # "BD_CruzVerde1783434975.jpg" -> "Cruz Verde"
        if n := nombre_desde_archivo(img["src"]):
            candidatos.append(n)
    for el in [card, *card.find_all(True)]:
        for attr in ("aria-label", "title", "data-name", "data-comercio", "data-title"):
            v = (el.get(attr) or "").strip()
            if 2 <= len(v) <= 50:
                candidatos.append(v)
    if m := RE_ANTES_PCT.match(texto):  # 3) "Avis Budget 20% descuento ..."
        candidatos.append(m.group(1))
    if m := RE_EN_COMERCIO.search(texto):  # 4) "25% Dcto. en OKAMI"
        candidatos.append(m.group(1))
    t_norm = normalizar(texto)  # 5) marcas conocidas mencionadas en el texto
    candidatos += [MARCAS[k] for k in MARCAS if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", t_norm)]
    textos(["p", "span"])  # 6) cualquier texto corto
    for c in candidatos:
        n = limpiar_nombre(c)
        # Títulos largos con signos de exclamación suelen ser frases de promoción
        if not es_generico(n) and "¡" not in n and len(n) <= 40:
            return n
    for c in candidatos:  # segunda pasada: aceptar un título de promoción
        n = limpiar_nombre(c)
        if not es_generico(n):
            return n
    return None


RE_LUGAR = re.compile(
    r"\b(?i:presencial)\s+(?i:en)\s+((?!Mallplaza\b)[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+(?:\s(?:y\s|del\s|de\s|la\s)?(?!(?:Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo|Hasta|Nuevo|Mañana|Hoy|Todos|Sin)\b)[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+)*)")


def extraer(html: str, banco: str, cfg: dict) -> list[Descuento]:
    soup = BeautifulSoup(html, "lxml")
    for b in soup(["script", "style", "noscript", "nav", "footer", "header"]):
        b.decompose()
    cards = soup.select(cfg["selector"]) if cfg.get("selector") else tarjetas_auto(soup)
    out: list[Descuento] = []
    for c in cards:
        texto = limpiar(c.get_text(" "))
        t_norm = normalizar(texto)
        if RE_NO_ES_DESCUENTO.search(t_norm) or RE_PRECIO_PRODUCTO.search(texto):
            continue
        pct, litro = parse_pct(texto)
        if pct is None:
            continue
        shop = nombre_comercio(c, cfg.get("titulo"), texto)
        if not shop:
            continue  # sin comercio identificable no sirve en la app
        a = c if c.name == "a" else c.find("a", href=True)
        link = urljoin(cfg["url"], a["href"]) if a and a.get("href") else cfg["url"]
        vig = RE_VIG.search(normalizar(texto))
        lugar = RE_LUGAR.search(texto)
        out.append(Descuento(
            shop=shop, cat=clasificar(f"{shop} {texto}"), bank=banco, pct=pct,
            days=parse_dias(texto) or list(range(7)),
            cond=corto(texto.replace(shop, "", 1)),
            perLitre=litro, upTo=bool(RE_HASTA.search(texto)),
            vig=f"Hasta {vig.group(1)}" if vig else "",
            loc=lugar.group(1) if lugar else "",
            url=link,
        ))
    return out


# ------------------------- adaptador Banco de Chile -------------------------
BCH_API = "/api/content/spaces/personas/types/beneficios/entries?per_page=100&page="
BCH_DETALLE = "https://sitiospublicos.bancochile.cl/personas/beneficios/detalle/"
TAG_DIAS = {"domingo": 0, "lunes": 1, "martes": 2, "miercoles": 3, "miércoles": 3,
            "jueves": 4, "viernes": 5, "sabado": 6, "sábado": 6}
TAG_NO_LUGAR = re.compile(r"-|metropolitana|segmentado|^todo|region|región")
BCH_CATEGORIAS = [
    ("beneficios/sabores", "comida"), ("beneficios/delivery", "comida"),
    ("beneficios/bienestar/belleza", "belleza"), ("beneficios/bienestar", "salud"),
    ("beneficios/panoramas", "entretenimiento"), ("beneficios/viajes", "viajes"),
]
RE_HTML = re.compile(r"<[^>]+>")


def bch_descargar(url: str) -> list[dict]:
    """Abre la página en un navegador real y pide la lista a la API del propio sitio."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        pag = nav.new_page(locale="es-CL")
        pag.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_S * 1000)
        try:
            pag.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        datos = pag.evaluate("""async (api) => {
            let todo = [], p = 1, total = 1;
            do {
                const r = await fetch(api + p).then(r => r.json());
                todo = todo.concat(r.entries || []);
                total = (r.meta && r.meta.total_pages) || 1;
                p++;
            } while (p <= total && p <= 30);
            return todo;
        }""", BCH_API)
        nav.close()
    return datos


def bch_convertir(e: dict) -> Descuento | None:
    meta, f = e.get("meta", {}), e.get("fields", {})
    fin = meta.get("unpublish_at")
    if fin:
        try:
            if datetime.fromisoformat(fin.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                return None
        except ValueError:
            pass
    shop = limpiar(f.get("Titulo") or meta.get("name") or "")
    tipo = f.get("Tipo Beneficio") or ""
    extracto = limpiar(f.get("Extracto") or "")
    desc = limpiar(RE_HTML.sub(" ", f.get("Descripcion") or ""))
    pct, litro = parse_pct(tipo.replace(";", " "))
    if pct is None:
        pct, litro = parse_pct(f"{extracto} {desc}")
    if pct is None or not shop:
        return None
    if RE_NO_ES_DESCUENTO.search(normalizar(f"{shop} {extracto}")):
        return None
    tags = [t.strip().lower() for t in meta.get("tags") or []]
    if "todos-los-dias" in tags:
        dias = list(range(7))
    else:
        dias = sorted({TAG_DIAS[t] for t in tags if t in TAG_DIAS}) or parse_dias(f"{extracto} {desc}") or list(range(7))
    lugares = [re.sub(r"\b(Del|De|La|Los|Las|Y)\b(?!$)", lambda m: m.group(1).lower(), t.title()).replace("La ", "La ", 1)
               for t in tags if t not in TAG_DIAS and not TAG_NO_LUGAR.search(t)]
    lugares = [l[:1].upper() + l[1:] for l in lugares]
    categoria = meta.get("category") or ""
    cat = next((c for pref, c in BCH_CATEGORIAS if categoria.startswith(pref)), None)
    if not cat:
        cat = "moda" if "vestuario-y-calzado" in tags else clasificar(f"{shop} {extracto} {f.get('Keywords') or ''}")
    vig = RE_VIG.search(normalizar(f.get("Vigencia") or ""))
    return Descuento(
        shop=shop[:60], cat=cat, bank="bchile", pct=pct, days=dias,
        cond=corto(extracto[:1].upper() + extracto[1:] if extracto else desc),
        perLitre=litro, upTo="hasta" in tipo.lower(),
        loc=", ".join(lugares[:3]),
        vig=f"Hasta {vig.group(1)}" if vig else "",
        url=BCH_DETALLE + meta.get("slug", "") if meta.get("slug") else BANCOS["bchile"]["url"],
    )


def adaptador_bchile(cfg: dict) -> list[Descuento]:
    datos = bch_descargar(cfg["url"])
    try:
        os.makedirs("debug", exist_ok=True)
        with open("debug/bchile-api.json", "w", encoding="utf-8") as fh:
            json.dump(datos[:20], fh, ensure_ascii=False, indent=1)  # muestra para revisar el formato
    except OSError:
        pass
    return [d for d in (bch_convertir(e) for e in datos) if d]


ADAPTADORES = {"bchile": adaptador_bchile}


# ------------------------------ mezcla ------------------------------------
def clave(d: dict) -> tuple:
    return (d["bank"], normalizar(d["shop"]), d["pct"], tuple(d["days"]))


DIAS_MAX_SIN_CONFIRMAR = 10


def vigente(d: dict) -> bool:
    """Descarta datos leídos hace mucho o que no pasan los filtros actuales."""
    if es_generico(d.get("shop", "")):
        return False
    if RE_NO_ES_DESCUENTO.search(normalizar(f"{d.get('shop', '')} {d.get('cond', '')}")):
        return False
    if RE_PRECIO_PRODUCTO.search(d.get("cond", "")):
        return False
    try:
        leido = datetime.fromisoformat(d.get("leido", "")).date()
        return (datetime.now(CHILE).date() - leido).days <= DIAS_MAX_SIN_CONFIRMAR
    except ValueError:
        return True


def mezclar(previos: list[dict], nuevos: dict[str, list[Descuento]]) -> list[dict]:
    manuales = [d for d in previos if d.get("origen") == "manual"]
    vistos = {clave(d) for d in manuales}
    resultado = list(manuales)
    for banco in BANCOS:
        if nuevos.get(banco):
            lista = [asdict(d) for d in nuevos[banco]]
        else:  # sin resultados: conservar lo anterior de ese banco (si sigue siendo válido)
            lista = [d for d in previos if d.get("origen") != "manual" and d["bank"] == banco and vigente(d)]
        for d in lista:
            if clave(d) not in vistos:
                vistos.add(clave(d))
                resultado.append(d)
    for i, d in enumerate(resultado):
        d["id"] = i
    return resultado


def guardar_copia(banco: str, html: str) -> None:
    """Guarda una copia liviana de la página en debug/ para poder revisar
    su estructura y ajustar selectores sin abrir el sitio."""
    try:
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "noscript", "svg", "iframe", "link", "meta"]):
            t.decompose()
        os.makedirs("debug", exist_ok=True)
        with open(os.path.join("debug", f"{banco}.html"), "w", encoding="utf-8") as f:
            f.write(soup.prettify()[:3_000_000])
    except Exception as e:
        log.warning("No se pudo guardar la copia de %s: %s", banco, e)


def scrapear(bancos: list[str]) -> dict[str, list[Descuento]]:
    res: dict[str, list[Descuento]] = {}
    for i, b in enumerate(bancos):
        cfg = BANCOS[b]
        if not cfg.get("activo", True):
            log.info("%-16s omitido (el sitio bloquea navegadores automáticos)", cfg["nombre"])
            continue
        if i:
            time.sleep(DELAY_S)
        try:
            if cfg.get("api"):
                res[b] = ADAPTADORES[cfg["api"]](cfg)
                log.info("%-16s %3d descuentos (API)", cfg["nombre"], len(res[b]))
            else:
                encontrados: list[Descuento] = []
                for j, url in enumerate(cfg.get("urls") or [cfg["url"]]):
                    c = {**cfg, "url": url}
                    html = bajar_html_js(url) if cfg.get("js") else bajar_html(url)
                    guardar_copia(b if j == 0 else f"{b}-{j}", html)
                    nuevos = extraer(html, b, c)
                    encontrados += nuevos
                    log.info("%-16s %3d descuentos en %s (%d KB)", cfg["nombre"], len(nuevos), url, len(html) // 1024)
                res[b] = encontrados
            if not res[b]:
                log.warning("  0 resultados: se conservan los anteriores")
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
