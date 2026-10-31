import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# Configuración de la página
st.set_page_config(
    page_title="Visualizador BCRP",
    page_icon="📈",
    layout="wide"
)

st.title("📊 Visualizador de Series Estadísticas del BCRP")
st.markdown("Esta aplicación web interactiva consume la API del BCRP para graficar series macroeconómicas de Perú.")

# Diccionario con algunas series populares del BCRP
SERIES_POPULARES = {
    "Tipo de Cambio - Venta (S/ por USD)": "PD04637PD",
    "Inflación (Variación % mensual IPC)": "PN01271PM",
    "Tasa de Interés de Referencia (%)": "PD04640PD",
    "PBI (Índice de volumen físico)": "PN01728AM"
}

# Barra lateral para selección de parámetros
st.sidebar.header("Configuración")
seleccion_nombre = st.sidebar.selectbox("Selecciona una serie estadística:", list(SERIES_POPULARES.keys()))
codigo_serie = SERIES_POPULARES[seleccion_nombre]

# Rango de años a consultar
anio_inicio = st.sidebar.slider("Año de inicio", 2010, 2026, 2020)
anio_fin = st.sidebar.slider("Año de fin", 2010, 2026, 2026)

# Función para obtener datos de la API de BCRP
@st.cache_data
def obtener_datos_bcrp(serie, start_year, end_year):
    # Formato de URL de la API del BCRP: https://estadisticas.bcrp.gob.pe/estadisticas/series/api/[codigo]/[formato]/[periodo-inicio]/[periodo-fin]
    url = f"https://estadisticas.bcrp.gob.pe/estadisticas/series/api/{serie}/json/{start_year}-1/{end_year}-12"
    try:
        response = requests.get(url)
        data = response.json()
        
        # Procesar los datos del JSON
        fechas = []
        valores = []
        for item in data['periods']:
            fechas.append(item['name'])
            # El BCRP a veces devuelve valores con formato de texto (ej. con comas), limpiamos
            val = item['values'][0]
            try:
                valores.append(float(val))
            except ValueError:
                valores.append(None)
                
        df = pd.DataFrame({
            'Fecha': fechas,
            'Valor': valores
        })
        # Eliminar nulos si existen
        df = df.dropna()
        return df
    except Exception as e:
        st.error(f"Error al conectar con la API del BCRP: {e}")
        return pd.DataFrame()

# Cargar datos
with st.spinner("Cargando datos del BCRP..."):
    df_datos = obtener_datos_bcrp(codigo_serie, anio_inicio, anio_fin)

if not df_datos.empty:
    # Mostrar métricas rápidas
    col1, col2, col3 = st.columns(3)
    col1.metric("Último Valor", f"{df_datos['Valor'].iloc[-1]:,.2f}", f"Fecha: {df_datos['Fecha'].iloc[-1]}")
    col2.metric("Valor Máximo en el Periodo", f"{df_datos['Valor'].max():,.2f}")
    col3.metric("Valor Mínimo en el Periodo", f"{df_datos['Valor'].min():,.2f}")

    # Crear gráfico interactivo con Plotly
    fig = px.line(
        df_datos, 
        x='Fecha', 
        y='Valor', 
        title=f"Evolución Histórica: {seleccion_nombre}",
        labels={'Valor': 'Valor', 'Fecha': 'Periodo'},
        template="plotly_white"
    )
    fig.update_traces(line_color='#008080', line_width=2.5)
    
    # Mostrar gráfico en la web
    st.plotly_chart(fig, use_container_width=True)
    
    # Mostrar tabla de datos si el usuario lo desea
    if st.checkbox("Ver tabla de datos raw"):
        st.dataframe(df_datos, use_container_width=True)
else:
    st.warning("No se encontraron datos para la serie o el periodo seleccionado.")
