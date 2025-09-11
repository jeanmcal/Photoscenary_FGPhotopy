# License: GPL 2

import sys
import os
import time
import xml.etree.ElementTree as ET
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import argparse
import shutil
import logging
from pathlib import Path
from PIL import Image
import subprocess
import numpy as np
import geopy.distance
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import math
from wand.image import Image as WandImage
from commons import (
    lat_deg_by_central_point, tile_width, index, x, y, coord_from_index, display_cursor_type_a,
    get_dds_size, get_png_size
)
from connector import (
    FGFSPositionRoute, get_fgfs_path_scenery, get_fgfs_position_lat, get_fgfs_position_lon,
    get_fgfs_position_set_task, telnet_connection_sock_is_open
)
from route import select_icao, load_route
from tiles_database import create_files_list_type_dds_and_png, copy_tiles_by_index, move_or_delete_tiles
import requests

# Program metadata
PROGRAM_VERSION = "0.4.2"
PROGRAM_VERSION_DATE = "20250908"
HOME_PROGRAM_PATH = os.getcwd()
UNCOMPLETED_TILES = {}

print(f"\nPhotoscenery.py version: {PROGRAM_VERSION} date: {PROGRAM_VERSION_DATE} - System prerequisite test\n")


def initialize_params_file() -> None:
    """Initialize or update the params.xml file with program version."""
    params_xml = None
    if os.path.exists("params.xml"):
        try:
            params_xml = ET.parse("params.xml")
            if params_xml.getroot().tag.lower() == "params":
                xroot = params_xml.getroot()
                versioning = xroot.find("versioning")
                if versioning is not None:
                    version_elem = versioning.find("version")
                    if version_elem is not None:
                        version_elem.text = PROGRAM_VERSION
        except ET.ParseError as e:
            print(f"Error: Failed to parse params.xml due to XML syntax error: {e}")
            print("Creating a new params.xml file...")
    
    if params_xml is None:
        params_xml = ET.ElementTree(ET.fromstring(
            f"<params><versioning><version>{PROGRAM_VERSION}</version><autor>Adriano Bassignana</autor><year>2021</year><licence>GPL 2</licence></versioning></params>"
        ))
    
    params_xml.write("params.xml")
    print("Initialized params.xml file")


def check_program_version() -> None:
    """Check and update program version in params.xml."""
    version_from_params = None
    try:
        if os.path.exists("params.xml"):
            params_xml = ET.parse("params.xml")
            if params_xml.getroot().tag.lower() == "params":
                xroot = params_xml.getroot()
                versioning = xroot.find("versioning")
                if versioning is not None and versioning.find("version") is not None:
                    version_from_params = versioning.find("version").text
    except ET.ParseError as e:
        print(f"Error: Failed to parse params.xml due to XML syntax error: {e}")
        print("Creating a new params.xml file...")
        initialize_params_file()
    
    if version_from_params is None or version_from_params != PROGRAM_VERSION:
        print(f"\nProgram version changed: old version {version_from_params} -> current version {PROGRAM_VERSION} ({PROGRAM_VERSION_DATE})")
        initialize_params_file()
    
    print('\nPhotoscenery Generator\nProgram for generating orthophoto files\n')


@dataclass
class MapServer:
    id: int
    web_url_base: str | None
    web_url_command: str | None
    name: str | None
    comment: str | None
    proxy: str | None
    error_code: int

    def __init__(self, id: int, proxy: str | None = None) -> None:
        """Initialize MapServer with configuration from params.xml."""
        try:
            tree = ET.parse("params.xml")
            servers_root = tree.find(".//servers")
            servers = servers_root.findall("server")
            for server in servers:
                if server.find("id").text.strip() == str(id):
                    self.id = id
                    self.web_url_base = server.find("url-base").text.strip()
                    self.web_url_command = server.find("url-command").text.strip().replace("|", "&")
                    self.name = server.find("name").text.strip()
                    self.comment = server.find("comment").text.strip()
                    self.proxy = proxy
                    self.error_code = 0
                    return
            self._set_default_values(id, proxy, error_code=410)
        except Exception as e:
            print(f"Error initializing MapServer: {e}")
            self._set_default_values(id, proxy, error_code=411)

    def _set_default_values(self, id: int, proxy: str | None, error_code: int) -> None:
        """Set default values for MapServer if configuration fails."""
        self.id = id
        self.web_url_base = None
        self.web_url_command = None
        self.name = None
        self.comment = None
        self.proxy = proxy
        self.error_code = error_code


@dataclass
class MapCoordinates:
    lat: float
    lon: float
    radius: float
    lat_ll: float
    lon_ll: float
    lat_ur: float
    lon_ur: float
    is_declare_polar: bool
    position_route: FGFSPositionRoute | None = None

    def __init__(self, lat: float, lon: float, radius: float = None, lat_ll: float = None, 
                 lon_ll: float = None, lat_ur: float = None, lon_ur: float = None) -> None:
        """Initialize MapCoordinates with either polar or bounding box coordinates."""
        if radius is not None:
            self.lat = lat
            self.lon = lon
            self.radius = radius
            self.lat_ll, self.lon_ll, self.lat_ur, self.lon_ur = lat_deg_by_central_point(lat, lon, radius)
            self.is_declare_polar = True
        else:
            self.lon = lon_ll + (lon_ur - lon_ll) / 2.0
            self.lat = lat_ll + (lat_ur - lat_ll) / 2.0
            lon_dist = abs(lon_ur - lon_ll) / 2.0
            lat_dist = abs(lat_ur - lat_ll) / 2.0
            pos_ll = (lat_ll, lon_ll)
            pos_ur = (lat_ur, lon_ur)
            self.radius = round(geopy.distance.geodesic(pos_ur, pos_ll).nautical, 2)
            self.lat_ll = lat_ll
            self.lon_ll = lon_ll
            self.lat_ur = lat_ur
            self.lon_ur = lon_ur
            self.is_declare_polar = False


def get_pixel_dimensions(size: int, size_dwn: int, radius: float, distance: float, 
                        position_route: FGFSPositionRoute | None, un_completed_tiles_attempts: int, 
                        latitude: float, debug_level: int) -> tuple[int, int, int, int]:
    """Calculate pixel dimensions, columns, and grid for tiles based on latitude and distance."""
    size_map_1to1 = {  # 1:1 aspect ratio for |lat| <= 22.5
        0: (512, 512, 1, 1),   # width, height, cols, grid_size
        1: (1024, 1024, 1, 1),
        2: (2048, 2048, 1, 1),
        3: (4096, 4096, 2, 2),
        4: (8192, 8192, 4, 4),
        5: (16384, 16384, 8, 8)
    }
    size_map_2to1 = {  # 2:1 aspect ratio for |lat| > 22.5
        0: (512, 256, 1, 1),
        1: (1024, 512, 1, 1),
        2: (2048, 1024, 1, 1),
        3: (4096, 2048, 2, 2),
        4: (8192, 4096, 4, 4),
        5: (16384, 8192, 8, 8)
    }
    size_map = size_map_1to1 if abs(latitude) <= 22.5 else size_map_2to1
    if size >= 3 and distance > radius / 2:
        if debug_level > 0:
            print(f"Debug: Using size=2 (2048x{'2048' if abs(latitude) <= 22.5 else '1024'}) for lat={latitude}, dist={distance}, radius={radius}")
        return size_map[2]
    
    default = (2048, 2048 if abs(latitude) <= 22.5 else 1024, 1, 1)
    selected_size = size_map.get(size, default)
    
    if debug_level > 0:
        aspect = '1:1' if abs(latitude) <= 22.5 else '2:1'
        print(f"Debug: Pixel dimensions for lat={latitude}, size={size}, aspect={aspect}, width={selected_size[0]}, height={selected_size[1]}, cols={selected_size[2]}, grid_size={selected_size[3]}")
    
    return selected_size


def adjust_pixel_size_by_distance(size: int, size_dwn: int, radius: float, distance: float, 
                                 position_route: FGFSPositionRoute | None, 
                                 un_completed_tiles_attempts: int, latitude: float, 
                                 debug_level: int) -> tuple[int, int, int, int]:
    """Adjust pixel size based on distance and altitude, prioritizing maximum resolution for the origin tile."""
    if size_dwn > size:
        size_dwn = size
    if un_completed_tiles_attempts > 0:
        size = max(0, min(5, size - un_completed_tiles_attempts))
        size_dwn = max(0, min(5, size_dwn - un_completed_tiles_attempts))
    
    altitude_nm = 0.0 if position_route is None or position_route.actual is None else position_route.actual.altitude_ft * 0.000164579
    relative_distance = math.sqrt(distance**2 + altitude_nm**2) / radius
    
    if debug_level > 0:
        print(f"Debug: Adjusting pixel size: dist={distance}, radius={radius}, relative_distance={relative_distance}, size={size}")
    
    if distance < 0.1:  # Ensure max resolution for the origin tile
        size_pixel_found = size
        if debug_level > 0:
            print(f"Debug: Origin tile detected (dist={distance}), using max size={size}")
    elif relative_distance < 0.1:  # Nearby tiles
        size_pixel_found = min(5, size)
    elif relative_distance < 0.3:  # Medium distance tiles
        size_pixel_found = min(4, size)
    else:  # Farther tiles
        size_pixel_found = int(round(size - (size - size_dwn) * relative_distance))
        size_pixel_found = max(size_dwn, min(size, size_pixel_found))
    
    return get_pixel_dimensions(size_pixel_found, size_dwn, radius, distance, position_route, 
                               un_completed_tiles_attempts, latitude, debug_level)


def generate_coordinate_matrix(map_coords: MapCoordinates, white_tile_index_list: dict | None, 
                              size: int, size_dwn: int, un_completed_tiles_attempts: int, 
                              position_route: FGFSPositionRoute | None, debug_level: int
                              ) -> tuple[list, int, MapCoordinates, bool]:
    """Generate a coordinate matrix for tiles, prioritizing the tile closest to the center."""
    number_of_tiles = 0
    lat_min = math.floor(map_coords.lat_ll)
    lon_min = math.floor(map_coords.lon_ll)
    lat_max = lat_min + 1.0
    lon_max = lon_min + 1.0

    lat_ll = max(map_coords.lat_ll, lat_min)
    lat_ur = min(map_coords.lat_ur, lat_max)
    lon_ll = max(map_coords.lon_ll, lon_min)
    lon_ur = min(map_coords.lon_ur, lon_max)

    if debug_level > 0:
        print(f"Debug: Coordinate matrix bounds: lat_ll={lat_ll:.3f}, lon_ll={lon_ll:.3f}, lat_ur={lat_ur:.3f}, lon_ur={lon_ur:.3f}")
        print(f"Debug: 1x1 tile bounds: lat_min={lat_min:.3f}, lon_min={lon_min:.3f}, lat_max={lat_max:.3f}, lon_max={lon_max:.3f}")

    tiles = []
    step_lat = 0.125
    step_lon = tile_width(map_coords.lat) / 1
    lat = lat_ll
    while lat < lat_ur:
        lon = lon_ll
        while lon < lon_ur:
            lon_block = int(math.floor(abs(lon) / 10) * 10) if lon >= 0.0 else int(math.ceil(abs(lon) / 10) * 10)
            lat_block = int(math.floor(abs(lat) / 10) * 10) if lat >= 0.0 else int(math.ceil(abs(lat) / 10) * 10)
            block_str = f"{'e' if lon >= 0.0 else 'w'}{lon_block:03d}{'n' if lat >= 0.0 else 's'}{lat_block:02d}"
            lon_str = f"{'e' if lon >= 0.0 else 'w'}{int(math.floor(abs(lon)) if lon >= 0.0 else math.ceil(abs(lon))):03d}"
            lat_str = f"{'n' if lat >= 0.0 else 's'}{int(math.floor(abs(lat)) if lat >= 0.0 else math.ceil(abs(lat))):02d}"
            tile_str = f"{lon_str}{lat_str}"
            
            tile_idx = index(lat, lon)
            if tile_idx is None:
                print(f"Error: Invalid tile index for lat={lat}, lon={lon}")
                lon += step_lon
                continue
            
            dist = round(geopy.distance.geodesic(
                (lat + 0.125/2.0, lon + step_lon/2.0),
                (map_coords.lat, map_coords.lon)
            ).nautical / 2.0, 3)
            size_pixel_w, size_pixel_h, cols_by_distance, grid_size = adjust_pixel_size_by_distance(
                size, size_dwn, map_coords.radius, dist, position_route, un_completed_tiles_attempts, 
                lat, debug_level
            )
            tiles.append((
                block_str, tile_str, lon, lon + step_lon, lat + 0.125, lat,
                tile_idx, x(lat, lon), y(lat), step_lon, dist, size_pixel_w, cols_by_distance, 
                size_pixel_h, grid_size
            ))
            if debug_level > 0:
                print(f"Debug: Tile id={tile_idx}, coords: lat={lat:.3f}, lon={lon:.3f}, x={x(lat, lon)}, y={y(lat)}, tile_width={step_lon:.3f}, size_pixel_w={size_pixel_w}, size_pixel_h={size_pixel_h}, grid_size={grid_size}, dist={dist}")
            lon += step_lon
        lat += step_lat
    
    # Prioritize the tile containing the center point
    player_tile = None
    min_dist = float('inf')
    for tile in tiles:
        tile_lat = tile[5]
        tile_lon = tile[2]
        tile_width_val = tile[9]
        if (tile_lat <= map_coords.lat < tile_lat + 0.125 and 
            tile_lon <= map_coords.lon < tile_lon + tile_width_val):
            player_tile = tile
            break
        if tile[10] < min_dist:
            min_dist = tile[10]
            player_tile = tile
    
    sorted_tiles = sorted(tiles, key=lambda x: x[10])
    grouped_tiles = []
    current_group = None
    previous_index = None
    counter_index = 0
    for tile in sorted_tiles:
        if white_tile_index_list is None or tile[6] in white_tile_index_list:
            if previous_index is None or previous_index != tile[6]:
                if current_group is not None:
                    grouped_tiles.append(current_group)
                current_group = []
                previous_index = tile[6]
                counter_index = 1
            else:
                counter_index += 1
            tile_data = (
                tile[0], tile[1], tile[2], tile[3], tile[4], tile[5], tile[6], counter_index,
                tile[9], 0, tile[10], tile[11], tile[12], tile[13], tile[14]
            )
            current_group.append(tile_data)
            current_group.append(0)
            number_of_tiles += 1
            if debug_level > 0:
                print(f"Tile id={tile_data[6]} coordinates: {tile_data[0]}/{tile_data[1]} | lon: {tile_data[2]:.6f} {tile_data[3]:.6f} lat: {tile_data[4]:.6f} {tile_data[5]:.6f} | Counter: {tile_data[7]} Width: {tile_data[8]:.6f} dist: {tile_data[10]} size: {tile_data[11]}x{tile_data[13]} grid: {tile_data[14]}x{tile_data[14]} | cols: {tile_data[12]}")
    if current_group:
        grouped_tiles.append(current_group)
    
    is_subtile = (lat_ur - lat_ll < 1.0) or (lon_ur - lon_ll < tile_width(lat_min))
    if debug_level > 0:
        print("\n----------")
        print("Coordinate Matrix Generator")
        print(f"Bounds: latLL={lat_ll:.3f}, lonLL={lon_ll:.3f}, latUR={lat_ur:.3f}, lonUR={lon_ur:.3f}")
        print(f"Number of tiles to process: {number_of_tiles}")
        print(f"Prioritized tile (closest to lat={map_coords.lat}, lon={map_coords.lon}): {grouped_tiles[0][0][6]} at {grouped_tiles[0][0][0]}/{grouped_tiles[0][0][1]}")
        print(f"Subtile mode: {is_subtile}")
        print("----------\n")
    
    return grouped_tiles, number_of_tiles, map_coords, is_subtile


def replace_url_placeholders(url_cmd: str, var_string: str, var_value: float, error_code: int) -> tuple[str, int]:
    """Replace placeholders in the map server URL command."""
    result = url_cmd.replace(var_string, f"{var_value:.6f}")
    if result == url_cmd:
        print(f"\nError: Invalid {var_string} in map server URL: {url_cmd}")
        return result, error_code + 1
    return result, error_code


def construct_map_server_url(map_server: MapServer, lat_ll: float, lon_ll: float, 
                            lat_ur: float, lon_ur: float, width: int, height: int) -> tuple[str, int]:
    """Construct the map server URL, using JPEG for high resolutions."""
    url_cmd = map_server.web_url_command
    error_code = map_server.error_code
    if error_code == 0:
        if width >= 4096:
            url_cmd = url_cmd.replace("format=png", "format=jpg")
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{latLL}", lat_ll, error_code)
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{lonLL}", lon_ll, error_code)
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{latUR}", lat_ur, error_code)
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{lonUR}", lon_ur, error_code)
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{szWidth}", width, error_code)
        url_cmd, error_code = replace_url_placeholders(url_cmd, "{szHight}", height, error_code)
        return map_server.web_url_base + url_cmd, 413 if error_code > 0 else 0
    return "", 412


def verify_imagemagick() -> tuple[bool, None]:
    """Verify if ImageMagick is accessible via Wand."""
    try:
        from wand.image import Image
        with Image() as img:
            print("\nImageMagick is operational via Wand!")
            return True, None
    except Exception as e:
        print(f"\nError: Failed to initialize ImageMagick via Wand: {e}")
        print("Please ensure ImageMagick is installed correctly.")
        print("Download from: https://imagemagick.org/script/download.php")
        print("On Windows, select 'Add application directory to your system path' and 'Install legacy utilities (e.g. convert)' during installation.")
        print("Restart your computer after installation.")
        return False, None


def get_absolute_file_path(file_name: str) -> str:
    """Construct an absolute file path relative to the program directory."""
    return os.path.normpath(os.path.join(HOME_PROGRAM_PATH, file_name))


def create_directory(root: str, path_level1: str, path_level2: str) -> str | None:
    """Create a directory path if it does not exist."""
    try:
        path = os.path.join(root, path_level1, path_level2)
        os.makedirs(path, exist_ok=True)
        return path
    except Exception as e:
        print(f"Error: Failed to create directory {root}: {e}")
        return None


def check_image_quality(image_path: str, debug_level: int) -> int:
    """Check the quality of an image based on its pixel count."""
    if os.path.isfile(image_path):
        try:
            with Image.open(image_path) as img:
                size_img = img.size[0] * img.size[1]
                if debug_level > 0:
                    print(f"Image quality check: {image_path} has {size_img} pixels")
                return size_img
        except Exception as e:
            if debug_level > 1:
                print(f"Error: Failed to check quality of {image_path}: {e}")
            return -2
    else:
        if debug_level > 1:
            print(f"Error: Image file {image_path} does not exist")
        return -1


def download_image(tile_data: tuple, lon_ll: float, lat_ll: float, delta_lat: float, 
                   delta_lon: float, size_pixel_w: int, size_pixel_h: int, path_save: str, 
                   map_server: MapServer, debug_level: int) -> tuple[bool, str | None]:
    """Download an image from the map server and save it."""
    global UNCOMPLETED_TILES
    url, error_code = construct_map_server_url(map_server, lat_ll, lon_ll, 
                                              lat_ll + delta_lat, lon_ll + delta_lon, 
                                              size_pixel_w, size_pixel_h)
    if error_code != 0:
        print(f"Error: Map server error code {error_code}")
        return False, None
    
    try:
        proxies = {"http": map_server.proxy, "https": map_server.proxy} if map_server.proxy else None
        response = requests.get(url, proxies=proxies, timeout=3000)
        if response.status_code == 200:
            file_name = get_absolute_file_path(f"temp_{tile_data[6]}.png")
            with open(file_name, "wb") as f:
                f.write(response.content)
            quality = check_image_quality(file_name, debug_level)
            if quality > 0:
                return True, file_name
            else:
                if os.path.exists(file_name):
                    os.remove(file_name)
                if debug_level > 0:
                    print(f"Image quality check failed for {file_name}")
                return False, None
        else:
            if debug_level > 0:
                print(f"Failed to download image from {url}, status code: {response.status_code}")
            return False, None
    except Exception as err:
        if debug_level > 0:
            print(f"Error downloading image from {url}: {err}")
        return False, None


def convert_png_to_dds(png_file: str, dds_file: str, debug_level: int, converter: str = "nvtt") -> bool:
    """Convert a PNG file to DDS format using the specified converter."""
    try:
        start_time = time.time()
        
        if converter.lower() == "nvtt":
            nvtt_export_path = r"C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvtt_export.exe"
            if not os.path.exists(nvtt_export_path):
                raise FileNotFoundError(f"NVTT exporter not found at {nvtt_export_path}")
            
            cmd = [nvtt_export_path, "--format", "bc3", "--output", dds_file, png_file]
            if debug_level > 0:
                print(f"Debug: Running NVTT command: {' '.join(cmd)}")
            subprocess.check_call(cmd, stderr=subprocess.STDOUT)
            if debug_level > 0:
                print(f"Converted {png_file} to {dds_file} with NVTT in {time.time() - start_time:.2f} seconds")
            return True
        
        elif converter.lower() == "imagemagick":
            cmd = [
                'magick', png_file,
                '-format', 'DDS',
                '-define', 'dds:compression=dxt5',
                '-define', 'dds:fast-mipmaps=true',
                '-quality', '50',
                dds_file
            ]
            if debug_level > 0:
                print(f"Debug: Running ImageMagick command: {' '.join(cmd)}")
            subprocess.check_call(cmd)
            if debug_level > 0:
                print(f"Converted {png_file} to {dds_file} with ImageMagick in {time.time() - start_time:.2f} seconds")
            return True
        
        else:
            raise ValueError(f"Invalid converter: {converter}. Use 'nvtt' or 'imagemagick'.")
    
    except FileNotFoundError as e:
        if debug_level > 0:
            print(f"Error: {e}. Ensure {'NVIDIA Texture Tools Exporter' if converter.lower() == 'nvtt' else 'ImageMagick'} is installed.")
        return False
    except subprocess.CalledProcessError as e:
        if debug_level > 0:
            print(f"Error converting {png_file} to DDS with {converter}: {e.output.decode() if e.output else str(e)}")
        return False
    except Exception as e:
        if debug_level > 0:
            print(f"Unexpected error converting {png_file} to DDS with {converter}: {e}")
        return False


def process_single_tile(tile_data: tuple, path_save: str, map_server: MapServer, size: int, 
                       format: int, debug_level: int, converter: str = "nvtt") -> bool:
    """Process a single tile by downloading sub-images and creating a mosaic."""
    try:
        tile_id = tile_data[6]
        lon_ll, lon_ur, lat_ur, lat_ll = tile_data[2], tile_data[3], tile_data[4], tile_data[5]
        size_pixel_w, cols_by_distance, size_pixel_h, grid_size = tile_data[11], tile_data[12], tile_data[13], tile_data[14]
        
        tile_dir = os.path.join(path_save, "Orthophotos", tile_data[0], tile_data[1])
        try:
            os.makedirs(tile_dir, exist_ok=True)
            if debug_level > 0:
                print(f"Created/verified directory: {tile_dir}")
        except Exception as e:
            if debug_level > 0:
                print(f"Error creating directory {tile_dir}: {e}")
            return False

        temp_png = os.path.join(path_save, f"temp_{tile_id}.png")
        output_file = os.path.join(tile_dir, f"{tile_id}.{'dds' if format == 1 else 'png'}")
        
        if os.path.exists(output_file):
            if debug_level > 0:
                print(f"Skipping existing tile: {output_file}")
            return True
        
        sub_width = size_pixel_w // grid_size
        sub_height = size_pixel_h // grid_size
        lon_step = (lon_ur - lon_ll) / grid_size
        lat_step = (lat_ur - lat_ll) / grid_size
        
        if debug_level > 0:
            print(f"Processing tile {tile_id}, size={size_pixel_w}x{size_pixel_h}, grid={grid_size}x{grid_size}, sub-image size={sub_width}x{sub_height}")
        
        sub_images_info = []
        for i in range(grid_size):
            for j in range(grid_size):
                sub_lon_ll = lon_ll + j * lon_step
                sub_lon_ur = sub_lon_ll + lon_step
                sub_lat_ur = lat_ur - i * lat_step
                sub_lat_ll = sub_lat_ur - lat_step
                sub_png = os.path.join(path_save, f"temp_{tile_id}_{i}_{j}.png")
                url, error_code = construct_map_server_url(map_server, sub_lat_ll, sub_lon_ll, 
                                                          sub_lat_ur, sub_lon_ur, sub_width, sub_height)
                if error_code != 0:
                    if debug_level > 0:
                        print(f"Failed to construct URL for sub-tile {tile_id}_{i}_{j}: Error code {error_code}")
                    return False
                sub_images_info.append((sub_png, url, tile_id, i, j))
        
        def download_sub_image(sub_info: tuple) -> str | None:
            """Download a sub-image with retry logic for robustness."""
            sub_png, url, tile_id, i, j = sub_info
            max_retries = 5
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://services.arcgisonline.com'
            }
            for attempt in range(max_retries):
                try:
                    with requests.get(url, stream=True, timeout=30, 
                                     proxies={"http": map_server.proxy, "https": map_server.proxy} if map_server.proxy else None, 
                                     headers=headers) as response:
                        response.raise_for_status()
                        with open(sub_png, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                    
                    if check_image_quality(sub_png, debug_level) > 0:
                        if debug_level > 0:
                            success, width, height = get_png_size(sub_png)
                            print(f"Debug: Downloaded sub-tile {sub_png}, dimensions={width}x{height}")
                        return sub_png
                    else:
                        os.remove(sub_png) if os.path.exists(sub_png) else None
                        if debug_level > 0:
                            print(f"Image quality check failed for sub-tile {sub_png}")
                        return None
                except requests.exceptions.HTTPError as err:
                    if response.status_code == 503:
                        if debug_level > 0:
                            print(f"503 Service Unavailable for sub-tile {tile_id}_{i}_{j} (attempt {attempt + 1}/{max_retries}): {url}")
                            if response.text:
                                print(f"Response content: {response.text[:200]}")
                        if attempt < max_retries - 1:
                            time.sleep(5 * (attempt + 1))
                            continue
                        os.remove(sub_png) if os.path.exists(sub_png) else None
                        return None
                    else:
                        if debug_level > 0:
                            print(f"HTTP error downloading sub-tile {tile_id}_{i}_{j}: {err}")
                        os.remove(sub_png) if os.path.exists(sub_png) else None
                        return None
                except requests.exceptions.Timeout:
                    if debug_level > 0:
                        print(f"Timeout downloading sub-tile {tile_id}_{i}_{j} (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(5 * (attempt + 1))
                        continue
                    os.remove(sub_png) if os.path.exists(sub_png) else None
                    return None
                except requests.exceptions.RequestException as err:
                    if debug_level > 0:
                        print(f"Error downloading sub-tile {tile_id}_{i}_{j}: {err}")
                    os.remove(sub_png) if os.path.exists(sub_png) else None
                    return None
            return None
        
        sub_images = []
        if debug_level > 0:
            print(f"Downloading {grid_size}x{grid_size} sub-images for tile {tile_id} in parallel")
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(download_sub_image, sub_info) for sub_info in sub_images_info]
            for future in futures:
                result = future.result()
                if result:
                    sub_images.append(result)
                else:
                    for sub_img in sub_images:
                        os.remove(sub_img) if os.path.exists(sub_img) else None
                    if debug_level > 0:
                        print(f"Failed to download one or more sub-images for tile {tile_id}")
                    return False
        
        if len(sub_images) != grid_size * grid_size:
            if debug_level > 0:
                print(f"Failed to download all {grid_size}x{grid_size} sub-images for tile {tile_id}")
            for sub_img in sub_images:
                os.remove(sub_img) if os.path.exists(sub_img) else None
            return False
        
        try:
            if debug_level > 0:
                print(f"Creating mosaic for tile {tile_id} with {grid_size}x{grid_size} sub-images")
            cmd = ['magick', 'montage'] + sub_images + ['-geometry', f'{sub_width}x{sub_height}+0+0', '-tile', f'{grid_size}x{grid_size}', temp_png]
            if debug_level > 0:
                print(f"Debug: Running command: {' '.join(cmd)}")
            subprocess.check_call(cmd)
            
            success, width, height = get_png_size(temp_png)
            if debug_level > 0:
                print(f"Debug: Mosaic PNG {temp_png}, dimensions={width}x{height}, expected={size_pixel_w}x{size_pixel_h}")
            
            if success and width == size_pixel_w and height == size_pixel_h:
                if format == 1:
                    if convert_png_to_dds(temp_png, output_file, debug_level, converter=converter):
                        if debug_level > 0:
                            success, width, height = get_dds_size(output_file)
                            print(f"Debug: Saved DDS {output_file}, dimensions={width}x{height}")
                        os.remove(temp_png)
                        for sub_img in sub_images:
                            os.remove(sub_img) if os.path.exists(sub_img) else None
                        return True
                    else:
                        if debug_level > 0:
                            print(f"Failed to convert {temp_png} to DDS for tile {tile_id}")
                        os.remove(temp_png) if os.path.exists(temp_png) else None
                        for sub_img in sub_images:
                            os.remove(sub_img) if os.path.exists(sub_img) else None
                        return False
                else:
                    shutil.move(temp_png, output_file)
                    if debug_level > 0:
                        success, width, height = get_png_size(output_file)
                        print(f"Debug: Saved PNG {output_file}, dimensions={width}x{height}")
                    for sub_img in sub_images:
                        os.remove(sub_img) if os.path.exists(sub_img) else None
                    return True
            else:
                if debug_level > 0:
                    print(f"Mosaic dimensions incorrect: expected {size_pixel_w}x{size_pixel_h}, got {width}x{height}")
                os.remove(temp_png) if os.path.exists(temp_png) else None
                for sub_img in sub_images:
                    os.remove(sub_img) if os.path.exists(sub_img) else None
                return False
        except subprocess.CalledProcessError as e:
            if debug_level > 0:
                print(f"Error creating mosaic for tile {tile_id}: {e}")
            os.remove(temp_png) if os.path.exists(temp_png) else None
            for sub_img in sub_images:
                os.remove(sub_img) if os.path.exists(sub_img) else None
            return False
    except Exception as err:
        if debug_level > 0:
            print(f"Error processing tile {tile_id}: {err}")
        os.remove(temp_png) if os.path.exists(temp_png) else None
        for sub_img in sub_images:
            os.remove(sub_img) if os.path.exists(sub_img) else None
        return False


def process_tiles(coordinates_matrix: list, map_coordinates: MapCoordinates, path_save: str, 
                 map_server: MapServer, size: int, size_dwn: int, format: int, 
                 position_route: FGFSPositionRoute | None, un_completed_tiles_attempts: int, 
                 debug_level: int, converter: str = "nvtt") -> tuple[int, int]:
    """Process tiles sequentially, updating pixel sizes dynamically."""
    global UNCOMPLETED_TILES
    number_of_tiles = 0
    processed_tiles = 0
    
    for tile_group in coordinates_matrix:
        for i in range(0, len(tile_group), 2):
            tile_data = tile_group[i]
            tile_id = tile_data[6]
            output_file = os.path.join(path_save, "Orthophotos", tile_data[0], tile_data[1], 
                                     f"{tile_id}.{'dds' if format == 1 else 'png'}")
            if os.path.exists(output_file):
                if debug_level > 0:
                    print(f"Skipping existing tile: {output_file}")
                processed_tiles += 1
                number_of_tiles += 1
                continue
            number_of_tiles += 1
            size_pixel_w, size_pixel_h, cols_by_distance, grid_size = adjust_pixel_size_by_distance(
                size, size_dwn, map_coordinates.radius, tile_data[10], position_route, 
                un_completed_tiles_attempts, tile_data[5], debug_level
            )
            tile_group[i] = tile_data[:-4] + (size_pixel_w, cols_by_distance, size_pixel_h, grid_size)
            if process_single_tile(tile_group[i], path_save, map_server, size, format, debug_level, converter):
                processed_tiles += 1
            if debug_level > 0:
                print(f"\rProcessing tiles: {processed_tiles}/{number_of_tiles} >", end="")
    
    if debug_level > 0:
        print(f"\nProcessed {processed_tiles} of {number_of_tiles} tiles")
    return processed_tiles, number_of_tiles


def main() -> None:
    """Main execution function for the photoscenery generator."""
    parser = argparse.ArgumentParser(description="Photoscenery Generator for FlightGear")
    parser.add_argument("-p", "--proxy", type=str, help="Proxy server (e.g., http://proxy:port)")
    parser.add_argument("-r", "--radius", type=float, default=10.0, help="Radius in nautical miles")
    parser.add_argument("-c", "--center", type=str, help="Center point as ICAO code or lat,lon (e.g., -45.66,9.7)")
    parser.add_argument("-b", "--bbox", type=str, help="Bounding box as latLL,lonLL,latUR,lonUR (e.g., -45.5,9.5,45.7,9.9)")
    parser.add_argument("-s", "--size", type=int, default=2, choices=range(7), 
                        help="Tile size (0=512, 1=1024, 2=2048, 3=4096, 4=8192, 5=16384, 6=32768)")
    parser.add_argument("-d", "--size_dwn", type=int, default=0, choices=range(7), 
                        help="Minimum tile size")
    parser.add_argument("-f", "--format", type=int, default=1, choices=[0, 1], 
                        help="Output format (0=PNG, 1=DDS)")
    parser.add_argument("-m", "--map_server", type=int, default=1, help="Map server ID")
    parser.add_argument("-o", "--output", type=str, default="C:\\Users\\Pc\\Documents\\Photoscenery", 
                        help="Output directory")
    parser.add_argument("-i", "--ip_port", type=str, default="127.0.0.1:5000", 
                        help="FlightGear Telnet IP:port")
    parser.add_argument("-t", "--route", type=str, help="Route file (FGFS or GPX)")
    parser.add_argument("-v", "--debug", type=int, default=0, help="Debug level (0-2)")
    parser.add_argument("--converter", type=str, default="nvtt", choices=["nvtt", "imagemagick"], 
                        help="Converter for DDS (nvtt or imagemagick)")
    args = parser.parse_args()

    # Validate output path
    try:
        path_save = os.path.normpath(args.output)
        os.makedirs(path_save, exist_ok=True)
        if not os.access(path_save, os.W_OK):
            print(f"Error: Output directory {path_save} is not writable")
            sys.exit(1)
        if args.debug > 0:
            print(f"Validated output directory: {path_save}")
    except Exception as e:
        print(f"Error: Failed to create or access output directory {args.output}: {e}")
        sys.exit(1)

    # Validate center coordinates
    if args.center:
        if "," in args.center and not args.center.lower().startswith("lim"):
            try:
                lat, lon = map(float, args.center.split(","))
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    print(f"Error: Invalid coordinates in --center: {args.center}. Latitude must be [-90, 90], longitude must be [-180, 180]")
                    sys.exit(1)
            except ValueError:
                print(f"Error: Invalid format for --center: {args.center}. Expected lat,lon (e.g., -45.66,9.7)")
                sys.exit(1)
    
    # Validate bounding box
    if args.bbox:
        try:
            lat_ll, lon_ll, lat_ur, lon_ur = map(float, args.bbox.split(","))
            if not (-90 <= lat_ll <= 90 and -180 <= lon_ll <= 180 and -90 <= lat_ur <= 90 and -180 <= lon_ur <= 180):
                print(f"Error: Invalid coordinates in --bbox: {args.bbox}. Latitudes must be [-90, 90], longitudes must be [-180, 180]")
                sys.exit(1)
        except ValueError:
            print(f"Error: Invalid format for --bbox: {args.bbox}. Expected latLL,lonLL,latUR,lonUR (e.g., -45.5,9.5,45.7,9.9)")
            sys.exit(1)

    # Initialize program
    check_program_version()
    is_imagemagick_ok, _ = verify_imagemagick()
    if not is_imagemagick_ok:
        print("Error: ImageMagick is not operational")
        sys.exit(1)

    # Initialize map server
    map_server = MapServer(args.map_server, args.proxy)
    if map_server.error_code != 0:
        print(f"Error: Map server configuration error, code: {map_server.error_code}")
        if args.debug > 0:
            print(f"MapServer: web_url_base={getattr(map_server, 'web_url_base', 'None')}, "
                  f"web_url_command={getattr(map_server, 'web_url_command', 'None')}, "
                  f"name={getattr(map_server, 'name', 'None')}")
        sys.exit(1)
    if args.debug > 0:
        print(f"MapServer: Initialized with web_url_base={map_server.web_url_base}, "
              f"web_url_command={map_server.web_url_command}, name={map_server.name}")

    # Set up output directory
    orthophotos_dir = os.path.join(path_save, "Orthophotos")
    os.makedirs(orthophotos_dir, exist_ok=True)
    if args.debug > 0:
        print(f"Output directory set to: {orthophotos_dir}")

    coordinates_matrix = None
    number_of_tiles = 0
    position_route = None
    map_coordinates = None
    is_subtile = False

    # Determine coordinates based on input arguments
    if args.route:
        route_list, route_size = load_route(args.route, args.radius)
        if route_size > 0:
            position_route = FGFSPositionRoute(args.radius, 0.5)
            position_route.marks = [(lat, lon, 0.0) for lat, lon, _ in route_list]
            position_route.size = route_size
            map_coordinates = MapCoordinates(route_list[0][0], route_list[0][1], args.radius)
            coordinates_matrix, number_of_tiles, map_coordinates, is_subtile = generate_coordinate_matrix(
                map_coordinates, None, args.size, args.size_dwn, 0, position_route, args.debug
            )
    elif args.center:
        if "," in args.center:
            lat, lon = map(float, args.center.split(","))
            map_coordinates = MapCoordinates(lat, lon, args.radius)
            coordinates_matrix, number_of_tiles, map_coordinates, is_subtile = generate_coordinate_matrix(
                map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
            )
        else:
            lat, lon, error_code = select_icao(args.center, args.radius)
            if error_code == 0:
                map_coordinates = MapCoordinates(lat, lon, args.radius)
                coordinates_matrix, number_of_tiles, map_coordinates, is_subtile = generate_coordinate_matrix(
                    map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
                )
            else:
                sys.exit(1)
    elif args.bbox:
        lat_ll, lon_ll, lat_ur, lon_ur = map(float, args.bbox.split(","))
        map_coordinates = MapCoordinates(0, 0, None, lat_ll, lon_ll, lat_ur, lon_ur)
        coordinates_matrix, number_of_tiles, map_coordinates, is_subtile = generate_coordinate_matrix(
            map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
        )
    else:
        lat = get_fgfs_position_lat(args.ip_port, args.debug)
        lon = get_fgfs_position_lon(args.ip_port, args.debug)
        if lat is not None and lon is not None:
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                if args.debug > 0:
                    print(f"Error: Invalid Telnet position (lat={lat}, lon={lon})")
                sys.exit(1)
            position_route = get_fgfs_position_set_task(args.ip_port, args.radius, 0.5, args.debug)
            map_coordinates = MapCoordinates(lat, lon, args.radius)
            coordinates_matrix, number_of_tiles, map_coordinates, is_subtile = generate_coordinate_matrix(
                map_coordinates, None, args.size, args.size_dwn, 0, position_route, args.debug
            )
        else:
            print("Error: Could not retrieve position from FlightGear")
            sys.exit(1)

    if coordinates_matrix:
        # Check if all tiles already exist
        all_tiles_exist = True
        tile_dir = None
        expected_tiles = []
        if is_subtile:
            lat_min = math.floor(map_coordinates.lat_ll)
            lon_min = math.floor(map_coordinates.lon_ll)
            step_lat = 0.125
            step_lon = tile_width(lat_min) / 8
            tile_str = f"{'e' if lon_min >= 0.0 else 'w'}{abs(int(lon_min)):03d}{'n' if lat_min >= 0.0 else 's'}{abs(int(lat_min)):02d}"
            tile_dir = os.path.join(orthophotos_dir, 
                                   f"{'e' if lon_min >= 0.0 else 'w'}{int(math.floor(abs(lon_min) / 10) * 10):03d}"
                                   f"{'n' if lat_min >= 0.0 else 's'}{int(math.floor(abs(lat_min) / 10) * 10):02d}", 
                                   tile_str)
            lat = lat_min
            while lat < lat_min + 1.0:
                lon = lon_min
                while lon < lon_min + tile_width(lat_min):
                    tile_idx = index(lat, lon)
                    if tile_idx:
                        expected_tiles.append(os.path.join(tile_dir, f"{tile_idx}.{'dds' if args.format == 1 else 'png'}"))
                    lon += step_lon
                lat += step_lat
        
        for tile_group in coordinates_matrix:
            for i in range(0, len(tile_group), 2):
                tile_data = tile_group[i]
                tile_id = tile_data[6]
                output_file = os.path.join(path_save, "Orthophotos", tile_data[0], tile_data[1], 
                                         f"{tile_id}.{'dds' if args.format == 1 else 'png'}")
                if not os.path.exists(output_file):
                    all_tiles_exist = False
                    break
            if not all_tiles_exist:
                break
        
        if all_tiles_exist:
            if is_subtile:
                all_subtiles_exist = all(os.path.exists(tile) for tile in expected_tiles)
                if all_subtiles_exist:
                    print(f"\nAll {len(expected_tiles)} sub-tiles already exist in {tile_dir}. Exiting.")
                    sys.exit(0)
            else:
                print(f"\nAll {number_of_tiles} tiles already exist in {orthophotos_dir}. Exiting.")
                sys.exit(0)

        processed_tiles, total_tiles = process_tiles(
            coordinates_matrix, map_coordinates, path_save, map_server, args.size, args.size_dwn,
            args.format, position_route, 0, args.debug, converter=args.converter
        )
        print(f"\nCompleted processing {processed_tiles} of {total_tiles} tiles")
        
        if args.bbox:
            if processed_tiles == total_tiles:
                print("Sub-tile processed successfully. Exiting.")
                sys.exit(0)
            else:
                print("Failed to process sub-tile. Exiting with error.")
                sys.exit(1)
        
        if processed_tiles == total_tiles:
            if is_subtile:
                all_subtiles_exist = all(os.path.exists(tile) for tile in expected_tiles)
                if all_subtiles_exist:
                    print(f"\nAll {len(expected_tiles)} sub-tiles processed successfully in {tile_dir}. Exiting.")
                    sys.exit(0)
                else:
                    print(f"\nNot all expected sub-tiles were processed. Exiting with error.")
                    sys.exit(1)
            else:
                print(f"\nAll {total_tiles} tiles processed successfully. Exiting.")
                sys.exit(0)
    else:
        print("Error: Failed to generate coordinate matrix")
        sys.exit(1)


if __name__ == "__main__":
    main()