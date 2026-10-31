import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Configuración de la página
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Visualizador BCRP", page_icon="📈", layout="wide")

st.title("📊 Visualizador de Series Estadísticas del BCRP")
st.markdown(
    "Aplicación interactiva que usa datos de **BCRPData** "
    "para graficar series macroeconómicas de Perú."
)

API_BASE = "https://estadisticas.bcrp.gob.pe/estadisticas/series/api"
DATA_DIR = Path(__file__).parent / "data"  # JSON guardados por actualizar_datos.py
ANIO_ACTUAL = datetime.now().year

# Series de ejemplo. El código termina en una letra que indica la frecuencia:
# D = diaria, M = mensual, Q = trimestral, A = anual.
SERIES_POPULARES = {
    "IPC Lima Metropolitana (var. % mensual)": "PN01271PM",
    "Tasa de referencia de la política monetaria (%)": "PD04722MM",
    "Tipo de cambio interbancario - Venta (S/ por US$)": "PD04638PD",
    "Otra serie (escribir código)": None,
}

FRECUENCIAS = {"D": "diaria", "M": "mensual", "Q": "trimestral", "A": "anual"}

MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8, "aug": 8,
    "set": 9, "sep": 9, "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-PE,es;q=0.9,en;q=0.8",
    "Referer": "https://estadisticas.bcrp.gob.pe/estadisticas/series/",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def frecuencia_de_codigo(codigo: str) -> str:
    """Deduce la frecuencia por la última letra del código (PN01271PM -> M)."""
    return FRECUENCIAS.get(codigo.strip().upper()[-1:], "mensual")


def construir_periodo(freq: str, anio_ini: int, anio_fin: int) -> str:
    """Formato de periodo que espera la API según la frecuencia."""
    hoy = datetime.now()
    if freq == "diaria":
        fin = f"{anio_fin}-12-31"
        if anio_fin >= hoy.year:
            fin = f"{hoy.year}-{hoy.month}-{hoy.day}"
        return f"{anio_ini}-1-1/{fin}"
    if freq == "mensual":
        return f"{anio_ini}-1/{anio_fin}-12"
    if freq == "trimestral":
        return f"{anio_ini}-1/{anio_fin}-4"
    return f"{anio_ini}/{anio_fin}"  # anual


def _anio(texto: str) -> int:
    n = int(texto)
    if len(texto) == 4:
        return n
    # Año de 2 dígitos: si cae muy en el futuro, es del siglo XX.
    return 2000 + n if 2000 + n <= ANIO_ACTUAL + 1 else 1900 + n


def parsear_fecha(texto: str):
    """Convierte 'Ene.2025', 'Ene25', '02Ene25', 'T1.2025' o '2025' en Timestamp."""
    s = re.sub(r"[\s.\-/]", "", str(texto).strip().lower())

    m = re.fullmatch(r"(\d{4})", s)  # anual
    if m:
        return pd.Timestamp(int(m.group(1)), 1, 1)

    m = re.fullmatch(r"t([1-4])(\d{2}|\d{4})", s) or re.fullmatch(
        r"([1-4])t(\d{2}|\d{4})", s
    )  # trimestral
    if m:
        return pd.Timestamp(_anio(m.group(2)), (int(m.group(1)) - 1) * 3 + 1, 1)

    m = re.fullmatch(r"(\d{1,2})?([a-z]{3,4})(\d{2}|\d{4})", s)  # diaria o mensual
    if m and m.group(2)[:3] in MESES:
        dia = int(m.group(1)) if m.group(1) else 1
        return pd.Timestamp(_anio(m.group(3)), MESES[m.group(2)[:3]], dia)

    return pd.NaT


def interpretar_respuesta(data: dict, codigo: str):
    """Convierte el JSON del BCRP en (DataFrame, título)."""
    periodos = data.get("periods") or []
    if not periodos:
        raise RuntimeError("La respuesta no trae datos para ese periodo.")

    filas = []
    for p in periodos:
        valores = p.get("values") or [None]
        filas.append((p.get("name"), valores[0]))
    df = pd.DataFrame(filas, columns=["Periodo", "Valor"])
    df["Fecha"] = df["Periodo"].map(parsear_fecha)
    df["Valor"] = pd.to_numeric(df["Valor"], errors="coerce")  # "n.d." -> NaN
    df = df.dropna(subset=["Fecha", "Valor"]).sort_values("Fecha").reset_index(drop=True)
    if df.empty:
        raise RuntimeError("Se recibieron datos pero no se pudieron interpretar las fechas o valores.")

    config = data.get("config") or {}
    series = config.get("series") or [{}]
    titulo = series[0].get("name") or config.get("title") or codigo
    return df[["Fecha", "Periodo", "Valor"]], titulo


def consultar_api(codigo: str, anio_ini: int, anio_fin: int):
    """Consulta en vivo. Devuelve (df, título, url). Lanza RuntimeError si falla."""
    periodo = construir_periodo(frecuencia_de_codigo(codigo), anio_ini, anio_fin)
    url = f"{API_BASE}/{codigo}/json/{periodo}/esp"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        raise RuntimeError(f"No se pudo conectar con el BCRP: {e}\nURL: {url}")
    if resp.status_code != 200:
        raise RuntimeError(f"El BCRP respondió con código {resp.status_code}.\nURL: {url}")
    try:
        data = resp.json()
    except ValueError:
        inicio = resp.text[:200].replace("\n", " ")
        raise RuntimeError(
            "El BCRP no devolvió JSON (posible bloqueo anti-bot o código/periodo "
            f"inválido).\nURL: {url}\nInicio de la respuesta: {inicio}"
        )
    try:
        df, titulo = interpretar_respuesta(data, codigo)
    except RuntimeError as e:
        raise RuntimeError(f"{e}\nURL: {url}")
    return df, titulo, url


def leer_respaldo(codigo: str, anio_ini: int, anio_fin: int):
    """Lee data/<codigo>.json. Devuelve (df, título, fecha_de_descarga)."""
    ruta = DATA_DIR / f"{codigo}.json"
    if not ruta.exists():
        raise FileNotFoundError(ruta.name)
    crudo = ruta.read_bytes()
    try:
        texto = crudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = crudo.decode("latin-1")
    guardado = json.loads(texto)
    # Acepta el formato de actualizar_datos.py ({"descargado", "respuesta"}) o el
    # JSON crudo del BCRP guardado directamente desde el navegador.
    if "respuesta" in guardado:
        data, dia = guardado["respuesta"], guardado.get("descargado")
    else:
        data, dia = guardado, None
    df, titulo = interpretar_respuesta(data, codigo)
    df = df[(df["Fecha"].dt.year >= anio_ini) & (df["Fecha"].dt.year <= anio_fin)]
    if df.empty:
        raise RuntimeError("Los datos guardados no cubren ese rango de años.")
    etiqueta = f"descargados el {dia}" if dia else "fecha de descarga no registrada"
    return df.reset_index(drop=True), titulo, etiqueta


@st.cache_data(ttl=3600, show_spinner=False)
def obtener_datos(codigo: str, anio_ini: int, anio_fin: int):
    """Intenta la API en vivo y, si falla, usa el respaldo guardado en el repositorio.

    Devuelve (df, título, url, fecha_respaldo, error_api). Si los datos vienen de la
    API en vivo, fecha_respaldo y error_api son None.
    """
    try:
        df, titulo, url = consultar_api(codigo, anio_ini, anio_fin)
        return df, titulo, url, None, None
    except RuntimeError as error_api:
        try:
            df, titulo, fecha = leer_respaldo(codigo, anio_ini, anio_fin)
        except (OSError, ValueError, KeyError, RuntimeError):
            raise error_api  # sin respaldo útil: mostrar el error de la API
        periodo = construir_periodo(frecuencia_de_codigo(codigo), anio_ini, anio_fin)
        url = f"{API_BASE}/{codigo}/json/{periodo}/esp"
        return df, titulo, url, fecha, str(error_api)


# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------
st.sidebar.header("Configuración")
nombre = st.sidebar.selectbox("Serie estadística:", list(SERIES_POPULARES.keys()))
codigo = SERIES_POPULARES[nombre]
if codigo is None:
    codigo = st.sidebar.text_input(
        "Código de la serie BCRPData", value="PN01288PM",
        help="Búscalo en estadisticas.bcrp.gob.pe. La última letra indica la frecuencia (D, M, Q, A).",
    ).strip().upper()

anio_ini, anio_fin = st.sidebar.slider(
    "Rango de años", 1995, ANIO_ACTUAL, (2018, ANIO_ACTUAL)
)

# ---------------------------------------------------------------------------
# Contenido principal
# ---------------------------------------------------------------------------
if not codigo:
    st.info("Escribe un código de serie en la barra lateral.")
    st.stop()

try:
    with st.spinner("Cargando datos del BCRP..."):
        df, titulo, url, fecha_respaldo, error_api = obtener_datos(codigo, anio_ini, anio_fin)
except RuntimeError as e:
    st.error("No se pudieron obtener los datos.")
    st.code(str(e))
    st.stop()

if fecha_respaldo:
    st.warning(
        f"La consulta en vivo al BCRP no está disponible desde este servidor, "
        f"así que se muestran los datos guardados en el repositorio (**{fecha_respaldo}**)."
    )
    with st.expander("Detalle del error de la consulta en vivo"):
        st.code(error_api)

ultimo = df.iloc[-1]
c1, c2, c3 = st.columns(3)
c1.metric("Último valor", f"{ultimo['Valor']:,.2f}")
c2.metric("Máximo en el periodo", f"{df['Valor'].max():,.2f}")
c3.metric("Mínimo en el periodo", f"{df['Valor'].min():,.2f}")
st.caption(f"Último dato: {ultimo['Periodo']} · Serie {codigo} ({frecuencia_de_codigo(codigo)})")

fig = px.line(
    df, x="Fecha", y="Valor", title=titulo, template="plotly_white",
    labels={"Valor": "Valor", "Fecha": "Periodo"},
)
fig.update_traces(line_color="#008080", line_width=2.5)
st.plotly_chart(fig)

with st.expander("Ver tabla de datos"):
    st.dataframe(df)
    st.download_button(
        "Descargar CSV", df.to_csv(index=False).encode("utf-8"),
        file_name=f"{codigo}.csv", mime="text/csv",
    )

st.caption(f"Fuente: BCRPData · [consulta a la API]({url})")
