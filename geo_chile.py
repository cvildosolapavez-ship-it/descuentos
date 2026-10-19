"""Comunas de Chile por región, para limpiar ubicaciones y filtrar por región.

Las claves de REGIONES son los códigos que usa la app.
"""
import re
import unicodedata

REGIONES = {
    "arica": "Arica y Parinacota", "tarapaca": "Tarapacá", "antofagasta": "Antofagasta",
    "atacama": "Atacama", "coquimbo": "Coquimbo", "valparaiso": "Valparaíso", "rm": "Metropolitana",
    "ohiggins": "O'Higgins", "maule": "Maule", "nuble": "Ñuble", "biobio": "Biobío",
    "araucania": "La Araucanía", "losrios": "Los Ríos", "loslagos": "Los Lagos", "aysen": "Aysén",
    "magallanes": "Magallanes",
}

_COMUNAS = {
    "arica": "Arica, Camarones, Putre, General Lagos",
    "tarapaca": "Iquique, Alto Hospicio, Pozo Almonte, Camiña, Colchane, Huara, Pica",
    "antofagasta": "Antofagasta, Mejillones, Sierra Gorda, Taltal, Calama, Ollagüe, San Pedro de Atacama, "
                   "Tocopilla, María Elena",
    "atacama": "Copiapó, Caldera, Tierra Amarilla, Chañaral, Diego de Almagro, Vallenar, Alto del Carmen, "
               "Freirina, Huasco",
    "coquimbo": "La Serena, Coquimbo, Andacollo, La Higuera, Paihuano, Vicuña, Illapel, Canela, Los Vilos, "
                "Salamanca, Ovalle, Combarbalá, Monte Patria, Punitaqui, Río Hurtado",
    "valparaiso": "Valparaíso, Casablanca, Concón, Juan Fernández, Puchuncaví, Quintero, Viña del Mar, "
                  "Isla de Pascua, Los Andes, Calle Larga, Rinconada, San Esteban, La Ligua, Cabildo, Papudo, "
                  "Petorca, Zapallar, Quillota, Calera, Hijuelas, La Cruz, Nogales, San Antonio, Algarrobo, "
                  "Cartagena, El Quisco, El Tabo, Santo Domingo, San Felipe, Catemu, Llaillay, Panquehue, "
                  "Putaendo, Santa María, Quilpué, Limache, Olmué, Villa Alemana",
    "rm": "Santiago, Cerrillos, Cerro Navia, Conchalí, El Bosque, Estación Central, Huechuraba, Independencia, "
          "La Cisterna, La Florida, La Granja, La Pintana, La Reina, Las Condes, Lo Barnechea, Lo Espejo, "
          "Lo Prado, Macul, Maipú, Ñuñoa, Pedro Aguirre Cerda, Peñalolén, Providencia, Pudahuel, Quilicura, "
          "Quinta Normal, Recoleta, Renca, San Joaquín, San Miguel, San Ramón, Vitacura, Puente Alto, "
          "Pirque, San José de Maipo, Colina, Lampa, Tiltil, San Bernardo, Buin, Calera de Tango, Paine, "
          "Melipilla, Alhué, Curacaví, María Pinto, San Pedro, Talagante, El Monte, Isla de Maipo, "
          "Padre Hurtado, Peñaflor",
    "ohiggins": "Rancagua, Codegua, Coinco, Coltauco, Doñihue, Graneros, Las Cabras, Machalí, Malloa, Mostazal, "
                "Olivar, Peumo, Pichidegua, Quinta de Tilcoco, Rengo, Requínoa, San Vicente, Pichilemu, La Estrella, "
                "Litueche, Marchigüe, Navidad, Paredones, San Fernando, Chépica, Chimbarongo, Lolol, Nancagua, "
                "Palmilla, Peralillo, Placilla, Pumanque, Santa Cruz",
    "maule": "Talca, Constitución, Curepto, Empedrado, Maule, Pelarco, Pencahue, Río Claro, San Clemente, "
             "San Rafael, Cauquenes, Chanco, Pelluhue, Curicó, Hualañé, Licantén, Molina, Rauco, Romeral, "
             "Sagrada Familia, Teno, Vichuquén, Linares, Colbún, Longaví, Parral, Retiro, San Javier, "
             "Villa Alegre, Yerbas Buenas",
    "nuble": "Chillán, Bulnes, Chillán Viejo, El Carmen, Pemuco, Pinto, Quillón, San Ignacio, Yungay, Quirihue, "
             "Cobquecura, Coelemu, Ninhue, Portezuelo, Ránquil, Treguaco, San Carlos, Coihueco, Ñiquén, "
             "San Fabián, San Nicolás",
    "biobio": "Concepción, Coronel, Chiguayante, Florida, Hualqui, Lota, Penco, San Pedro de la Paz, Santa Juana, "
              "Talcahuano, Tomé, Hualpén, Lebu, Arauco, Cañete, Contulmo, Curanilahue, Los Álamos, Tirúa, "
              "Los Ángeles, Antuco, Cabrero, Laja, Mulchén, Nacimiento, Negrete, Quilaco, Quilleco, San Rosendo, "
              "Santa Bárbara, Tucapel, Yumbel, Alto Biobío",
    "araucania": "Temuco, Carahue, Cunco, Curarrehue, Freire, Galvarino, Gorbea, Lautaro, Loncoche, Melipeuco, "
                 "Nueva Imperial, Padre Las Casas, Perquenco, Pitrufquén, Pucón, Saavedra, Teodoro Schmidt, "
                 "Toltén, Vilcún, Villarrica, Cholchol, Angol, Collipulli, Curacautín, Ercilla, Lonquimay, "
                 "Los Sauces, Lumaco, Purén, Renaico, Traiguén, Victoria",
    "losrios": "Valdivia, Corral, Lanco, Los Lagos, Máfil, Mariquina, Paillaco, Panguipulli, La Unión, "
               "Futrono, Lago Ranco, Río Bueno",
    "loslagos": "Puerto Montt, Calbuco, Cochamó, Fresia, Frutillar, Los Muermos, Llanquihue, Maullín, "
                "Puerto Varas, Castro, Ancud, Chonchi, Curaco de Vélez, Dalcahue, Puqueldón, Queilén, Quellón, "
                "Quemchi, Quinchao, Osorno, Puerto Octay, Purranque, Puyehue, Río Negro, San Juan de la Costa, "
                "San Pablo, Chaitén, Futaleufú, Hualaihué, Palena",
    "aysen": "Coyhaique, Lago Verde, Aysén, Cisnes, Guaitecas, Cochrane, O'Higgins, Tortel, Chile Chico, Río Ibáñez",
    "magallanes": "Punta Arenas, Laguna Blanca, Río Verde, San Gregorio, Cabo de Hornos, Antártica, Porvenir, "
                  "Primavera, Timaukel, Natales, Torres del Paine",
}

# Localidades, apodos y errores de escritura frecuentes -> comuna oficial
_ALIAS = {
    "chicureo": "Colina", "pte alto": "Puente Alto", "sn bernardo": "San Bernardo", "maipu": "Maipú",
    "renaca": "Viña del Mar", "reñaca": "Viña del Mar", "vina": "Viña del Mar", "con con": "Concón",
    "chiloe": "Castro", "chilechico": "Chile Chico", "huelpen": "Hualpén", "hualpen": "Hualpén",
    "san joaquin": "San Joaquín", "santiago centro": "Santiago", "stgo": "Santiago", "borderio": "Vitacura",
    "open kennedy": "Las Condes", "mallplaza tobalaba": "Puente Alto", "la union": "La Unión",
    "los angeles": "Los Ángeles", "ritoque": "Quintero", "la calera": "Calera", "curacavi": "Curacaví",
    "san pedro": "San Pedro de la Paz", "puerto natales": "Natales", "coyhaique": "Coyhaique",
    "coihaique": "Coyhaique", "la ligua": "La Ligua", "pichilemu": "Pichilemu", "frutillar": "Frutillar",
}

# Nombres de región como aparecen en los sitios de los bancos
_REGION_ALIAS = {
    "arica y parinacota": "arica", "tarapaca": "tarapaca", "atacama": "atacama",
    "metropolitana de santiago": "rm", "metropolitana": "rm", "region metropolitana": "rm", "r.m.": "rm",
    "rm": "rm", "r.m": "rm", "libertador general bernardo o'higgins": "ohiggins", "o'higgins": "ohiggins",
    "ohiggins": "ohiggins", "maule": "maule", "nuble": "nuble", "biobio": "biobio", "bio bio": "biobio",
    "la araucania": "araucania", "araucania": "araucania", "los rios": "losrios", "los lagos": "loslagos",
    "aysen del general carlos ibanez del campo": "aysen", "aysen": "aysen",
    "magallanes y de la antartica chilena": "magallanes", "magallanes": "magallanes",
    # Numeración romana (Ripley usa "VIII Región", "X Región")
    "xv region": "arica", "i region": "tarapaca", "ii region": "antofagasta", "iii region": "atacama",
    "iv region": "coquimbo", "v region": "valparaiso", "vi region": "ohiggins", "vii region": "maule",
    "xvi region": "nuble", "viii region": "biobio", "ix region": "araucania", "xiv region": "losrios",
    "x region": "loslagos", "xi region": "aysen", "xii region": "magallanes",
}
# Nombres que son a la vez región y comuna: se tratan como comuna (más preciso)
_AMBIGUOS = {"valparaiso", "antofagasta", "coquimbo"}

NACIONAL = re.compile(r"todo[- ]chile|todo el pais|a nivel nacional|online|en linea|sitio web|app\b|delivery|despacho", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip(" .,-")


COMUNA_REGION: dict[str, tuple[str, str]] = {}
for _reg, _lista in _COMUNAS.items():
    for _c in _lista.split(", "):
        COMUNA_REGION.setdefault(_norm(_c), (_c, _reg))
for _a, _c in _ALIAS.items():
    COMUNA_REGION[_norm(_a)] = COMUNA_REGION[_norm(_c)]


def ubicar(textos: list[str]) -> tuple[list[str], list[str]]:
    """Recibe fragmentos de ubicación ('Las Condes', 'R.M. (Vitacura / La Reina)', 'los lagos')
    y devuelve (comunas reconocidas, códigos de región). Lo que no reconoce se descarta."""
    comunas, regiones = [], []

    def add(lista, v):
        if v not in lista:
            lista.append(v)

    for t in textos:
        for parte in re.split(r"[,/;()]|\s+y\s+|\s+-\s+", t or ""):
            n = _norm(parte)
            if not n:
                continue
            m = re.match(r"^([ivx]+)\s+region\b", n)
            if m and f"{m.group(1)} region" in _REGION_ALIAS:
                add(regiones, _REGION_ALIAS[f"{m.group(1)} region"])
            elif n in _REGION_ALIAS and n not in _AMBIGUOS:
                add(regiones, _REGION_ALIAS[n])
            elif n in COMUNA_REGION:
                nombre, reg = COMUNA_REGION[n]
                add(comunas, nombre)
                add(regiones, reg)
    # "Valparaíso" junto a "Viña del Mar" suele ser la región, no la comuna
    for amb in ("Valparaíso", "Antofagasta", "Coquimbo"):
        if amb in comunas:
            reg = COMUNA_REGION[_norm(amb)][1]
            if any(COMUNA_REGION[_norm(c)][1] == reg for c in comunas if c != amb):
                comunas.remove(amb)
    return comunas, regiones
