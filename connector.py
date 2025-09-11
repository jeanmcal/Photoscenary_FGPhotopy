# License: GPL 2
# Program for reading the aircraft position via Telnet protocol over TCP-IP.

import socket
import xml.etree.ElementTree as ET
import time
from dataclasses import dataclass
import geopy.distance

@dataclass
class TelnetConnection:
    ip_address: str
    ip_port: int
    sock: socket.socket | None = None
    telnet_data: list = None

    def __init__(self, address: str):
        self.ip_address, self.ip_port = get_fgfs_position_ip_and_port(address)
        self.telnet_data = []

@dataclass
class FGFSPosition:
    latitude_deg: float
    longitude_deg: float
    altitude_ft: float
    direction_deg: float = 0.0
    distance_nm: float = 0.0
    speed_mph: float = 0.0
    time: float = None

    def __init__(self, lat: float, lon: float, alt: float, prec_position: 'FGFSPosition' = None):
        self.latitude_deg = lat
        self.longitude_deg = lon
        self.altitude_ft = alt
        self.time = time.time()
        if prec_position:
            try:
                dir_deg = geopy.distance.geodesic(
                    (prec_position.latitude_deg, prec_position.longitude_deg),
                    (lat, lon)
                ).bearing
                dist = geopy.distance.geodesic(
                    (prec_position.latitude_deg, prec_position.longitude_deg),
                    (lat, lon)
                ).nautical
                delta_time = self.time - prec_position.time
                speed_mph = (dist - prec_position.distance_nm) * 3600 / delta_time if delta_time > 0 else 0.0
                self.direction_deg = dir_deg
                self.distance_nm = dist
                self.speed_mph = speed_mph
            except Exception as err:
                print(f"FGFSPosition - Error: {err}")
                self.direction_deg = prec_position.direction_deg
                self.distance_nm = prec_position.distance_nm
                self.speed_mph = prec_position.speed_mph

@dataclass
class FGFSPositionRoute:
    marks: list = None
    size: int = 0
    actual: FGFSPosition | None = None
    prec_position: FGFSPosition | None = None
    actual_distance: float = 0.0
    actual_speed: float = 0.0
    actual_direction_deg: float = 0.0
    radius_step: float = 0.0
    radius_step_factor: float = 0.5
    step_time: float = 2.0
    telnet_last_time: float = 0.0
    telnet: TelnetConnection | None = None

    def __init__(self, central_point_radius_distance, radius_step_factor=0.5):
        self.marks = []
        self.radius_step = central_point_radius_distance
        self.radius_step_factor = radius_step_factor

def telnet_connection_sock_is_open(telnet):
    """Check if Telnet connection is open."""
    try:
        return telnet is not None and telnet.sock is not None and not telnet.sock._closed
    except AttributeError:
        return False

def get_fgfs_position_ip_and_port(ip_address_and_port: str) -> tuple[str, int]:
    """Parse IP address and port."""
    s = ip_address_and_port.split(":")
    ip = "127.0.0.1"
    port = 5000
    if len(s) > 1:
        try:
            port = int(s[1])
        except ValueError:
            pass
    if len(s[0]) > 0:
        ip = s[0]
    return ip, port

def set_fgfs_connect(telnet: TelnetConnection, debug_level: int):
    """Establish Telnet connection asynchronously."""
    import threading
    def connect_task():
        try:
            if not telnet_connection_sock_is_open(telnet):
                telnet.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                telnet.sock.connect((telnet.ip_address, telnet.ip_port))
                time.sleep(0.5)
                if debug_level > 1:
                    print(f"setFGFSConnect - First connection {telnet.ip_address}:{telnet.ip_port}")
            while telnet_connection_sock_is_open(telnet):
                line = telnet.sock.recv(1024).decode().strip()
                if line:
                    telnet.telnet_data.append(line)
        except Exception as err:
            telnet.sock = None
            if debug_level > 1:
                print(f"setFGFSConnect - connection ended with error {err}")
    threading.Thread(target=connect_task, daemon=True).start()
    return telnet

def get_fgfs_values(s: str, type_of_data: str):
    """Parse Telnet data."""
    try:
        a = s.split("=")
        value = a[1].split("'")[1]
        return float(value) if type_of_data == 'f' else value
    except Exception:
        return None

def get_fgfs_path_scenery(ip_address_and_port: str, debug_level: int):
    """Get FlightGear scenery path via Telnet."""
    try:
        retray = 1
        telnet = set_fgfs_connect(TelnetConnection(ip_address_and_port), debug_level)
        time.sleep(0.5)
        while telnet_connection_sock_is_open(telnet) and retray <= 10:
            time.sleep(0.1)
            if retray == 1:
                telnet.sock.send("get /sim/fg-scenery\r\n".encode())
            if telnet.telnet_data:
                return get_fgfs_values(telnet.telnet_data[0], 's')
            retray += 1
        if debug_level > 1:
            print("\ngetFGFSPathScenery - Sockets is close")
        return None
    except Exception as err:
        if debug_level > 1:
            print(f"\ngetFGFSPathScenery - Error connection: {err}")
        return None

def get_fgfs_position_lat(ip_address_and_port: str, debug_level: int):
    """Get latitude via Telnet."""
    try:
        retray = 1
        telnet = set_fgfs_connect(TelnetConnection(ip_address_and_port), debug_level)
        time.sleep(0.5)
        while telnet_connection_sock_is_open(telnet) and retray <= 10:
            time.sleep(0.1)
            if retray == 1:
                telnet.sock.send("get /position/latitude-deg\r\n".encode())
            if telnet.telnet_data:
                return get_fgfs_values(telnet.telnet_data[0], 'f')
            retray += 1
        if debug_level > 1:
            print("\ngetFGFSPositionLat - Sockets is close")
        return None
    except Exception as err:
        if debug_level > 1:
            print(f"\ngetFGFSPositionLat - Error connection: {err}")
        return None

def get_fgfs_position_lon(ip_address_and_port: str, debug_level: int):
    """Get longitude via Telnet."""
    try:
        retray = 1
        telnet = set_fgfs_connect(TelnetConnection(ip_address_and_port), debug_level)
        time.sleep(0.5)
        while telnet_connection_sock_is_open(telnet) and retray <= 10:
            time.sleep(0.1)
            if retray == 1:
                telnet.sock.send("get /position/longitude-deg\r\n".encode())
            if telnet.telnet_data:
                return get_fgfs_values(telnet.telnet_data[0], 'f')
            retray += 1
        if debug_level > 1:
            print("\ngetFGFSPositionLon - Sockets is close")
        return None
    except Exception as err:
        if debug_level > 1:
            print(f"\ngetFGFSPositionLon - Error connection: {err}")
        return None

def get_fgfs_position(telnet: TelnetConnection, prec_position: FGFSPosition | None, debug_level: int):
    """Get aircraft position via Telnet."""
    telnet.telnet_data = []
    try:
        retray = 1
        while telnet_connection_sock_is_open(telnet) and retray <= 3:
            telnet.sock.send("dump /position\r\n".encode())
            time.sleep(0.5)
            if len(telnet.telnet_data) >= 8:
                telnet_data_xml = "".join(telnet.telnet_data[1:])
                try:
                    root = ET.fromstring(telnet_data_xml)
                    lat = float(root.find(".//latitude-deg").text)
                    lon = float(root.find(".//longitude-deg").text)
                    alt = float(root.find(".//altitude-ft").text)
                    ground_elev = float(root.find(".//ground-elev-ft").text)
                    alt -= ground_elev
                    return FGFSPosition(lat, lon, alt, prec_position)
                except Exception as err:
                    if debug_level > 1:
                        print(f"\ngetFGFSPosition - Error in XML: {err}")
                    return None
            retray += 1
        if debug_level > 1:
            print("\ngetFGFSPosition - Sockets is close")
        return None
    except Exception as err:
        if debug_level > 1:
            print(f"\ngetFGFSPosition - Error connection: {err}")
        return None

def get_fgfs_position_set_task(ip_address_and_port: str, central_point_radius_distance: float, radius_step_factor: float, debug_level: int):
    """Asynchronously track aircraft position."""
    import threading
    position_route = FGFSPositionRoute(central_point_radius_distance, radius_step_factor)
    max_retray = 10

    def task(position_route):
        """Task to update position via Telnet."""
        global marks_update
        import time
        while True:
            if not telnet_connection_sock_is_open(position_route.telnet):
                position_route.telnet = None
                marks_update = False
                return
            try:
                position_route.telnet.write(b"get /position/latitude-deg\r\n")
                lat = float(position_route.telnet.read_until(b"\r\n", 1).decode().split("=")[1])
                position_route.telnet.write(b"get /position/longitude-deg\r\n")
                lon = float(position_route.telnet.read_until(b"\r\n", 1).decode().split("=")[1])
                position_route.telnet.write(b"get /position/altitude-ft\r\n")
                alt = float(position_route.telnet.read_until(b"\r\n", 1).decode().split("=")[1])
                marks_update = True
                position_route.marks.append((lat, lon, alt))
                position_route.marks = position_route.marks[-position_route.size:]
            except Exception:
                position_route.telnet = None
                marks_update = False
                return
            time.sleep(position_route.time)

    threading.Thread(target=task, args=(position_route,), daemon=True).start()
    return position_route