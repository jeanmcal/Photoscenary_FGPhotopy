# License: GPL 3

import xml.etree.ElementTree as ET
import unicodedata
import pandas as pd
import pickle
import geopy.distance
from commons import find_file, in_value, coord_from_index
import os

def find_file_of_route(file_name: str, id_type_of_file: int = 0):
    """Find route file and determine its type."""
    type_of_file = [("FGFS", "route"), ("GPX", "rte")]
    date = 0.0
    file_id = 0
    route = None
    type_of_file_selected = None
    files = find_file(file_name)
    
    for file in files:
        if file[2] >= date:
            try:
                tree = ET.parse(file[1])
                root = tree.getroot()
                # Set the namespace for GPX
                ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}
                
                if id_type_of_file > 0:
                    route = root.findall(f".//{type_of_file[id_type_of_file-1][1]}", namespaces=ns if type_of_file[id_type_of_file-1][0] == "GPX" else None)
                    type_of_file_selected = type_of_file[id_type_of_file-1][0]
                else:
                    for name_format, selector in type_of_file:
                        if name_format == "GPX":
                            route = root.findall(f".//gpx:{selector}", namespaces=ns)
                        else:
                            route = root.findall(f".//{selector}")
                        type_of_file_selected = name_format
                        if route:
                            break
                file_id = file[0]
                date = file[2]
            except ET.ParseError as e:
                print(f"Error: Failed to parse {file[1]}: {e}")
                continue
            except Exception as e:
                print(f"Error: Unexpected error processing {file[1]}: {e}")
                continue
    if file_id > 0:
        return route, files[file_id-1][1], type_of_file_selected
    print(f"Error: No valid route file found for {file_name}")
    return None, None, None

def select_icao(icao_to_select, central_point_radius_distance):
    """Select latitude and longitude by ICAO code, name, or municipality."""
    central_point_lat = None
    central_point_lon = None
    error_code = 0
    retray_number = 0

    while retray_number <= 1:
        airports_csv = "airports.csv"
        airports_jls = "airports.jls"
        if os.path.exists(airports_csv) and (not os.path.exists(airports_jls) or os.path.getmtime(airports_csv) > os.path.getmtime(airports_jls)):
            print("\nThe airports database 'airports.csv' is loading for conversion to airports.jls file")
            df = pd.read_csv(airports_csv)
            with open(airports_jls, "wb") as f:
                pickle.dump(df, f)
            print("The airports database 'airports.jls' is converted")
        elif not os.path.exists(airports_jls):
            print("\nError: The airports.jls file and airports.csv file are unreachable!\nPlease, make sure it is present in the photoscenery program directory")
            error_code = 403
            retray_number = 9

        if error_code == 0:
            try:
                with open(airports_jls, "rb") as f:
                    db = pickle.load(f)
                search_string = unicodedata.normalize("NFKD", icao_to_select.upper()).encode("ASCII", "ignore").decode("ASCII")
                found_data = db[db["ident"] == search_string]
                if len(found_data) == 0:
                    found_data = db[db["municipality"].str.normalize("NFKD").str.upper().str.encode("ASCII", "ignore").str.decode("ASCII").str.contains(search_string, na=False)]
                if len(found_data) == 0:
                    found_data = db[db["name"].str.normalize("NFKD").str.upper().str.encode("ASCII", "ignore").str.decode("ASCII").str.contains(search_string, na=False)]
                
                if len(found_data) == 1:
                    if central_point_radius_distance is None or central_point_radius_distance <= 1.0:
                        central_point_radius_distance = 10.0
                    central_point_lat = found_data.iloc[0]["latitude_deg"]
                    central_point_lon = found_data.iloc[0]["longitude_deg"]
                    if not (in_value(central_point_lat, 90) and in_value(central_point_lon, 180)):
                        if abs(central_point_lat) > 1000.0:
                            central_point_lat /= 1000.0
                        if abs(central_point_lon) > 1000.0:
                            central_point_lon /= 1000.0
                    print(f"\nThe ICAO term {icao_to_select} is found in the database\n\tIdent: {found_data.iloc[0]['ident']}\n\tName: {found_data.iloc[0]['name']}\n\tCity: {found_data.iloc[0]['municipality']}\n\tCentral point lat: {round(central_point_lat, 4)} lon: {round(central_point_lon, 4)} radius: {central_point_radius_distance} nm")
                else:
                    if len(found_data) > 1:
                        error_code = 401
                        print(f"\nError: The ICAO search term {icao_to_select} is ambiguous, there are {len(found_data)} airports with a similar term")
                        for i in range(min(len(found_data), 30)):
                            print(f"\tId: {found_data.iloc[i]['ident']}\tname: {found_data.iloc[i]['name']} ({found_data.iloc[i]['municipality']})")
                    else:
                        error_code = 400
                        print(f"\nError: The ICAO search term {icao_to_select} is not found in the airports.csv database")
                retray_number = 9
            except Exception as err:
                if retray_number == 0:
                    retray_number = 1
                    print("\nError: The airports.csv file is corrupt or does not exist")
                    error_code = 403
                else:
                    print(f"\nError: The airports.csv file is corrupt\n\tPlease, make sure if airports.csv file is present in the program directory\n\tand restart the program\nError code is {err}")
                    error_code = 404
                    retray_number = 9
        if retray_number == 0:
            retray_number = 9
    return central_point_lat, central_point_lon, error_code

def get_route_list_format_fgfs(route_list, route, min_distance):
    """Parse FGFS route format and populate route list."""
    wps = route[0].findall(".//wp")
    central_point_lat_prec = None
    central_point_lon_prec = None
    for wp in wps:
        found_data = False
        if wp is not None:
            icao_elem = wp.find("icao")
            if icao_elem is not None:
                icao = icao_elem.text.strip()
                central_point_lat, central_point_lon, error_code = select_icao(icao, min_distance)
                if error_code == 0:
                    found_data = True
            elif wp.find("lon") is not None:
                central_point_lat = float(wp.find("lat").text.strip())
                central_point_lon = float(wp.find("lon").text.strip())
                found_data = True
            if found_data:
                if central_point_lat_prec is not None and central_point_lon_prec is not None:
                    distance_nm = geopy.distance.geodesic(
                        (central_point_lat_prec, central_point_lon_prec),
                        (central_point_lat, central_point_lon)
                    ).nautical
                else:
                    distance_nm = 0.0
                if min_distance < distance_nm:
                    number_trunk = int(round(distance_nm / min_distance))
                    for i in range(1, number_trunk):
                        deg_lat = central_point_lat_prec + i * (central_point_lat - central_point_lat_prec) / number_trunk
                        deg_lon = central_point_lon_prec + i * (central_point_lon - central_point_lon_prec) / number_trunk
                        dist = geopy.distance.geodesic(
                            (deg_lat, deg_lon),
                            (central_point_lat_prec, central_point_lon_prec)
                        ).nautical
                        route_list.append((deg_lat, deg_lon, dist))
                        print(f"Load Route step {len(route_list)}.{i} coordinates lat: {round(route_list[-1][0], 4)} lon: {round(route_list[-1][1], 4)} distance: {round(dist, 1)}")
                route_list.append((central_point_lat, central_point_lon, distance_nm))
                print(f"Load Route step {len(route_list)}.0 coordinates lat: {round(route_list[-1][0], 4)} lon: {round(route_list[-1][1], 4)} distance: {round(distance_nm, 1)}")
                central_point_lat_prec = central_point_lat
                central_point_lon_prec = central_point_lon
    return route_list

def get_route_list_format_gpx(route_list, route, min_distance):
    """Parse GPX route format and populate route list."""
    ns = {'gpx': 'http://www.topografix.com/GPX/1/1'}  # Namespace for GPX
    central_point_lat_prec = None
    central_point_lon_prec = None
    if not route:
        print("Error: No <rte> elements found in GPX file")
        return route_list
    
    wps = route[0].findall(".//gpx:rtept", namespaces=ns)
    if not wps:
        print("Error: No <rtept> elements found in GPX file")
        return route_list
    
    for wp in wps:
        if wp is not None and wp.get("lon") is not None and wp.get("lat") is not None:
            try:
                central_point_lat = float(wp.get("lat").strip())
                central_point_lon = float(wp.get("lon").strip())
                if central_point_lat_prec is not None and central_point_lon_prec is not None:
                    distance_nm = geopy.distance.geodesic(
                        (central_point_lat_prec, central_point_lon_prec),
                        (central_point_lat, central_point_lon)
                    ).nautical
                else:
                    distance_nm = 0.0
                if min_distance < distance_nm:
                    number_trunk = int(round(distance_nm / min_distance))
                    for i in range(1, number_trunk):
                        deg_lat = central_point_lat_prec + i * (central_point_lat - central_point_lat_prec) / number_trunk
                        deg_lon = central_point_lon_prec + i * (central_point_lon - central_point_lon_prec) / number_trunk
                        dist = geopy.distance.geodesic(
                            (deg_lat, deg_lon),
                            (central_point_lat_prec, central_point_lon_prec)
                        ).nautical
                        route_list.append((deg_lat, deg_lon, dist))
                        print(f"Load Route step {len(route_list)}.{i} coordinates lat: {round(route_list[-1][0], 4)} lon: {round(route_list[-1][1], 4)} distance: {round(dist, 1)}")
                route_list.append((central_point_lat, central_point_lon, distance_nm))
                print(f"Load Route step {len(route_list)}.0 coordinates lat: {round(route_list[-1][0], 4)} lon: {round(route_list[-1][1], 4)} distance: {round(distance_nm, 1)}")
                central_point_lat_prec = central_point_lat
                central_point_lon_prec = central_point_lon
            except ValueError as e:
                print(f"Error: Invalid lat/lon values in GPX waypoint: {wp.get('lat')}, {wp.get('lon')}: {e}")
    return route_list

def load_route(file_of_route, central_point_radius_distance):
    """Load route from file."""
    central_point_radius_distance_factor = 0.5
    min_distance = central_point_radius_distance * central_point_radius_distance_factor
    route, file_path, type_of_file = find_file_of_route(file_of_route)
    route_list = []
    if route is not None:
        if type_of_file == "FGFS":
            get_route_list_format_fgfs(route_list, route, min_distance)
        elif type_of_file == "GPX":
            get_route_list_format_gpx(route_list, route, min_distance)
    else:
        print(f"\nError: loadRoute in the route file: {file_of_route}")
    return route_list, len(route_list)