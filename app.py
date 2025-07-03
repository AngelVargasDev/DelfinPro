import streamlit as st
import pandas as pd
import numpy as np
import googlemaps
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from datetime import datetime

# ---- 1. Parámetros globales ----
API_KEY = st.secrets["googlemaps"]["api_key"]  # Cambiado para Streamlit Cloud
gmaps = googlemaps.Client(key=API_KEY)

# Coordenadas UPCA
UPCA_LAT, UPCA_LON = 10.987173, -74.819437

# ---- 2. Carga y preprocesa Excel ----
st.title("Optimizador de Ruta de Hospitales")
archivo = st.file_uploader("Sube el archivo Excel con hospitales", type=["xlsx"])

if archivo:
    df = pd.read_excel(archivo)
    df.columns = df.columns.str.strip()

    # Extrae lat/lon de columna WKT
    def extraer_lat_lon(wkt):
        wkt = wkt.strip().replace("POINT", "").replace("(", "").replace(")", "")
        parts = wkt.split()
        if len(parts) >= 2:
            lon = float(parts[0])
            lat = float(parts[1])
            return pd.Series([lat, lon])
        else:
            return pd.Series([None, None])

    df[["lat", "lon"]] = df["WKT"].apply(extraer_lat_lon)
    st.write("Hospitales encontrados:", df[["ID", "Nombre", "lat", "lon"]])

    # ---- 3. Selección de hospitales ----
    opciones = [f'{row["ID"]} - {row["Nombre"]}' for _, row in df.iterrows()]
    seleccion = st.multiselect("Selecciona hospitales a visitar:", opciones)

    if seleccion:
        # Toma solo los seleccionados
        seleccion_ids = [s.split(" - ")[0] for s in seleccion]
        seleccionados = df[df["ID"].isin(seleccion_ids)].copy()

        # Siempre UPCA al inicio y final
        hospitales = []
        hospitales.append(("UPCA", "Centro de Acopio", UPCA_LAT, UPCA_LON))
        for _, row in seleccionados.iterrows():
            hospitales.append((row["ID"], row["Nombre"], row["lat"], row["lon"]))
        hospitales.append(("UPCA", "Centro de Acopio", UPCA_LAT, UPCA_LON))

        locations = [(lat, lon) for _, _, lat, lon in hospitales]

        # ---- 4. Matriz de tiempos con tráfico ----
        now = datetime.now()
        n = len(locations)
        matriz = np.zeros((n, n))
        loc_strs = [f"{lat},{lon}" for lat, lon in locations]

        for i, origin in enumerate(loc_strs):
            response = gmaps.distance_matrix(
                [origin], loc_strs,
                mode="driving",
                departure_time=now,
                traffic_model="best_guess"
            )
            for j, element in enumerate(response["rows"][0]["elements"]):
                matriz[i, j] = element.get("duration_in_traffic", {}).get("value", 1e9)

        # ---- 5. Soluciona TSP ----
        manager = pywrapcp.RoutingIndexManager(n, 1, 0)
        routing = pywrapcp.RoutingModel(manager)

        def dist_callback(from_index, to_index):
            return int(matriz[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)])

        transit_callback_index = routing.RegisterTransitCallback(dist_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)

        solution = routing.SolveWithParameters(search_parameters)

        ruta = []
        if solution:
            index = routing.Start(0)
            while not routing.IsEnd(index):
                ruta.append(manager.IndexToNode(index))
                index = solution.Value(routing.NextVar(index))
            ruta.append(manager.IndexToNode(index))

            st.subheader("Orden óptimo de visita:")
            for i, idx in enumerate(ruta):
                st.write(f"{i+1}. {hospitales[idx][0]} - {hospitales[idx][1]}")

            # Genera URL de Google Maps
            url = "https://www.google.com/maps/dir/" + "/".join(
                [f"{hospitales[idx][2]},{hospitales[idx][3]}" for idx in ruta]
            )
            st.markdown(f"[Ver ruta en Google Maps]({url})")
        else:
            st.warning("No se pudo resolver la ruta óptima.")
