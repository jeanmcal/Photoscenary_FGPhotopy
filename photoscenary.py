# License: GPL 3

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

version_program = "0.4.00"
version_program_date = "20230523"
home_program_path = os.getcwd()
un_completed_tiles = {}

print(f"\nPhotoscenary.py ver: {version_program} date: {version_program_date} System prerequisite test\n")

def initialize_params():
    """Initialize params.xml file."""
    params_xml = None
    if os.path.exists("params.xml"):
        params_xml = ET.parse("params.xml")
        if params_xml.getroot().tag.lower() == "params":
            xroot = params_xml.getroot()
            versioning = xroot.find("versioning")
            if versioning is not None:
                version_elem = versioning.find("version")
                if version_elem is not None:
                    version_elem.text = version_program
    if params_xml is None:
        params_xml = ET.ElementTree(ET.fromstring(
            f"<params><versioning><version>{version_program}</version><autor>Adriano Bassignana</autor><year>2021</year><licence>GPL 2</licence></versioning></params>"
        ))
    params_xml.write("params.xml")

def initialize():
    """Initialize program and check version."""
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
        initialize_params()
    
    if version_from_params is None or version_from_params != version_program:
        print(f"\nThe program version is changed old version is {version_from_params} the actual version is {version_program} ({version_program_date})")
        initialize_params()
    print('\nPhotoscenery generator by Python,\nProgram for uploading Orthophotos files\n')
    return None  

@dataclass
class MapServer:
    id: int
    web_url_base: str | None
    web_url_command: str | None
    name: str | None
    comment: str | None
    proxy: str | None
    error_code: int

    def __init__(self, id: int, a_proxy: str | None = None):
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
                    self.proxy = a_proxy
                    self.error_code = 0
                    return
            self.id = id
            self.web_url_base = None
            self.web_url_command = None
            self.name = None
            self.comment = None
            self.proxy = None
            self.error_code = 410
        except Exception:
            self.id = id
            self.web_url_base = None
            self.web_url_command = None
            self.name = None
            self.comment = None
            self.proxy = None
            self.error_code = 411

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

    def __init__(self, lat: float, lon: float, radius: float = None, lat_ll: float = None, lon_ll: float = None, lat_ur: float = None, lon_ur: float = None):
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

def get_size_pixel(size, size_dwn, radius, dist, position_route, un_completed_tiles_attemps, lat, debug_level):
    """Calculate pixel size, columns, and grid for tiles, mimicking FGJulia with latitude-based aspect ratio."""
    size_map_1to1 = {  # Proporção 1:1 para |lat| <= 22.5
        0: (512, 512, 1, 1),   # width, height, cols, grid_size
        1: (1024, 1024, 1, 1),
        2: (2048, 2048, 1, 1),
        3: (4096, 4096, 2, 2),
        4: (8192, 8192, 4, 4),
        5: (16384, 16384, 8, 8)
    }
    size_map_2to1 = {  # Proporção 2:1 para |lat| > 22.5
        0: (512, 256, 1, 1),   # width, height, cols, grid_size
        1: (1024, 512, 1, 1),
        2: (2048, 1024, 1, 1),
        3: (4096, 2048, 2, 2),
        4: (8192, 4096, 4, 4),
        5: (16384, 8192, 8, 8)
    }
    # Choose map sizes based on latitude
    size_map = size_map_1to1 if abs(lat) <= 22.5 else size_map_2to1
    if size >= 3 and dist > radius / 2:
        if debug_level > 0:
            print(f"Debug - get_size_pixel: lat={lat}, dist={dist}, radius={radius}, using size=2 (2048x{'2048' if abs(lat) <= 22.5 else '1024'})")
        return size_map[2][0], size_map[2][1], size_map[2][2], size_map[2][3]
    default = (2048, 2048 if abs(lat) <= 22.5 else 1024, 1, 1)
    selected_size = size_map.get(size, default)
    if debug_level > 0:
        print(f"Debug - get_size_pixel: lat={lat}, size={size}, aspect={'1:1' if abs(lat) <= 22.5 else '2:1'}, size_pixel_w={selected_size[0]}, size_pixel_h={selected_size[1]}, cols={selected_size[2]}, grid_size={selected_size[3]}")
    return selected_size[0], selected_size[1], selected_size[2], selected_size[3]

def get_size_pixel_width_by_distance(size, size_dwn, radius, distance, position_route, un_completed_tiles_attemps, lat, debug_level):
    """Adjust pixel size based on distance and altitude, ensuring maximum resolution for the origin tile."""
    if size_dwn > size:
        size_dwn = size
    if un_completed_tiles_attemps > 0:
        size = max(0, min(5, size - un_completed_tiles_attemps))
        size_dwn = max(0, min(5, size_dwn - un_completed_tiles_attemps))
    
    altitude_nm = 0.0 if position_route is None or position_route.actual is None else position_route.actual.altitude_ft * 0.000164579
    relative_distance = math.sqrt(distance**2 + altitude_nm**2) / radius
    
    if debug_level > 0:
        print(f"Debug - get_size_pixel_width_by_distance: dist={distance}, radius={radius}, relative_distance={relative_distance}, size={size}")
    
    # Ensure maximum resolution for the source tile (distance close to 0)
    if distance < 0.001:  # Consider the source tile when the distance is almost zero
        size_pixel_found = size  # Use the maximum resolution set by -s
        if debug_level > 0:
            print(f"Debug - get_size_pixel_width_by_distance: Origin tile detected (dist={distance}), using max size={size}")
    elif relative_distance < 0.1:  # Tiles too close
        size_pixel_found = min(5, size)  # Maximum resolution
    elif relative_distance < 0.3:  # Nearby tiles
        size_pixel_found = min(4, size)  # Intermediate resolution
    else:  # Farthest tiles
        size_pixel_found = int(round(size - (size - size_dwn) * relative_distance))
        size_pixel_found = max(size_dwn, min(size, size_pixel_found))
    
    return get_size_pixel(size_pixel_found, size_dwn, radius, distance, position_route, un_completed_tiles_attemps, lat, debug_level)

def coordinate_matrix_generator(m: MapCoordinates, white_tile_index_list_dict, size, size_dwn, un_completed_tiles_attemps, position_route, is_debug):
    """Generate coordinate matrix for tiles, prioritizing the tile closest to the initial lat/lon."""
    number_of_tiles = 0
    lat_ll = m.lat_ll - (m.lat_ll % 0.125)
    lat_ur = m.lat_ur - (m.lat_ur % 0.125) + 0.125
    lon_ll = m.lon_ll - (m.lon_ll % tile_width(m.lat))
    lon_ur = m.lon_ur - (m.lon_ur % tile_width(m.lat)) + tile_width(m.lat)
    
    if is_debug > 0:
        print(f"Debug - coordinate_matrix_generator: lat_ll={lat_ll}, lon_ll={lon_ll}, lat_ur={lat_ur}, lon_ur={lon_ur}")
    
    a = []
    lat = lat_ll
    while lat <= lat_ur:
        lon = lon_ll
        while lon <= lon_ur:
            lon_block = int(math.floor(abs(lon) / 10) * 10) if lon >= 0.0 else int(math.ceil(abs(lon) / 10) * 10)
            lat_block = int(math.floor(abs(lat) / 10) * 10) if lat >= 0.0 else int(math.ceil(abs(lat) / 10) * 10)
            block_str = f"{'e' if lon >= 0.0 else 'w'}{lon_block:03d}{'n' if lat >= 0.0 else 's'}{lat_block:02d}"
            lon_str = f"{'e' if lon >= 0.0 else 'w'}{int(math.floor(abs(lon)) if lon >= 0.0 else math.ceil(abs(lon))):03d}"
            lat_str = f"{'n' if lat >= 0.0 else 's'}{int(math.floor(abs(lat)) if lat >= 0.0 else math.ceil(abs(lat))):02d}"
            tile_str = f"{lon_str}{lat_str}"
            
            tile_idx = index(lat, lon)
            if tile_idx is None:
                print(f"Error - coordinate_matrix_generator: Invalid tile index for lat={lat}, lon={lon}")
                lon += tile_width(lat)
                continue
            
            dist = round(geopy.distance.geodesic(
                (lat + 0.125/2.0, lon + tile_width(lat)/2.0),
                (m.lat, m.lon)
            ).nautical / 2.0, 3)
            size_pixel_w, size_pixel_h, cols_by_distance, grid_size = get_size_pixel(size, size_dwn, m.radius, dist, position_route, un_completed_tiles_attemps, lat=lat, debug_level=is_debug)
            a.append((
                block_str, tile_str, lon, lon + tile_width(lat), lat + 0.125, lat,
                tile_idx, x(lat, lon), y(lat), tile_width(lat), dist, size_pixel_w, cols_by_distance, size_pixel_h, grid_size
            ))
            if is_debug > 0:
                print(f"Debug - Tile id: {tile_idx}, coords: lat={lat}, lon={lon}, x={x(lat, lon)}, y={y(lat)}, tile_width={tile_width(lat)}, size_pixel_w={size_pixel_w}, size_pixel_h={size_pixel_h}, grid_size={grid_size}, dist={dist}")
            lon += tile_width(lat)
        lat += 0.125
    
    a_sort = sorted(a, key=lambda x: x[10])
    d = []
    c = None
    prec_index = None
    counter_index = 0
    for b in a_sort:
        if white_tile_index_list_dict is None or (white_tile_index_list_dict and b[6] in white_tile_index_list_dict):
            if prec_index is None or prec_index != b[6]:
                if c is not None:
                    d.append(c)
                c = []
                prec_index = b[6]
                counter_index = 1
            else:
                counter_index += 1
            t = (b[0], b[1], b[2], b[3], b[4], b[5], b[6], counter_index, b[9], 0, b[10], b[11], b[12], b[13], b[14])
            c.append(t)
            c.append(0)
            number_of_tiles += 1
            if is_debug > 0:
                print(f"Tile id: {t[6]} coordinates: {t[0]} {t[1]} | lon: {t[2]:.6f} {t[3]:.6f} lat: {t[4]:.6f} {t[5]:.6f} | Counter: {t[7]} Width: {t[8]:.6f} dist: {t[10]} size: {t[11]}x{t[13]} grid: {t[14]}x{t[14]} | {t[12]}")
    if c:
        d.append(c)
    
    if is_debug > 0:
        print("\n----------")
        print("CoordinateMatrix generator")
        print(f"latLL: {lat_ll} lonLL {lon_ll} latUR: {lat_ur} lonUR {lon_ur}\n")
        print(f"Number of tiles to process: {number_of_tiles}")
        print(f"Prioritized tile (closest to lat: {m.lat}, lon: {m.lon}): {d[0][0][6]} at {d[0][0][0]}/{d[0][0][1]}")
        print("----------\n")
    return d, number_of_tiles, m

def get_map_server_replace(url_cmd, var_string, var_value, error_code):
    """Replace placeholders in URL command."""
    a = url_cmd.replace(var_string, f"{var_value:.6f}")
    if a != url_cmd:
        return a, error_code
    print(f"\nError: getMapServerReplace params.xml has problems in the servers section\n\tthe map server with id has the {var_string} value not correct or defined\n\t{url_cmd}")
    return a, error_code + 1

def get_map_server(m: MapServer, lat_ll, lon_ll, lat_ur, lon_ur, sz_width, sz_height):
    """Construct map server URL, using JPEG for high resolutions."""
    url_cmd = m.web_url_command
    error_code = m.error_code
    if error_code == 0:
        if sz_width >= 4096:
            url_cmd = url_cmd.replace("format=png", "format=jpg")
        url_cmd, error_code = get_map_server_replace(url_cmd, "{latLL}", lat_ll, 0)
        url_cmd, error_code = get_map_server_replace(url_cmd, "{lonLL}", lon_ll, error_code)
        url_cmd, error_code = get_map_server_replace(url_cmd, "{latUR}", lat_ur, error_code)
        url_cmd, error_code = get_map_server_replace(url_cmd, "{lonUR}", lon_ur, error_code)
        url_cmd, error_code = get_map_server_replace(url_cmd, "{szWidth}", sz_width, error_code)
        url_cmd, error_code = get_map_server_replace(url_cmd, "{szHight}", sz_height, error_code)
        return m.web_url_base + url_cmd, 413 if error_code > 0 else 0
    return "", 412

def check_image_magick(image_magick_path):
    """Check if Wand can access ImageMagick."""
    try:
        from wand.image import Image
        with Image() as img:  # Test Wand startup
            print("\nImageMagick is operative via Wand!")
            return True, None
    except Exception as e:
        print(f"\nError: Failed to initialize Wand with ImageMagick: {e}")
        print("Please ensure ImageMagick is installed correctly.")
        print("Download from: https://imagemagick.org/script/download.php")
        print("On Windows, select 'Add application directory to your system path' and 'Install legacy utilities (e.g. convert)' during installation.")
        print("After installation, restart your computer.")
        return False, None

def file_with_root_home_path(file_name):
    """Construct file path with home directory."""
    return os.path.normpath(os.path.join(home_program_path, file_name))

def set_path(root, path_liv1, path_liv2):
    """Create directory path."""
    try:
        path = os.path.join(root, path_liv1, path_liv2)
        os.makedirs(path, exist_ok=True)
        return path
    except Exception:
        print(f"The {root} directory is inexistent, the directory will be created")
        return None

def image_quality(image, debug_level):
    """Analyze image quality."""
    if os.path.isfile(image):
        try:
            with Image.open(image) as img:
                size_img = img.size[0] * img.size[1]
                if debug_level > 0:
                    print(f"imageQuality - The file {image} is downloaded the size is: {size_img}")
                return size_img
        except Exception:
            if debug_level > 1:
                print(f"Error: imageQuality - The file {image} is not downloaded")
            return -2
    else:
        if debug_level > 1:
            print(f"Error: imageQuality - The file {image} is not present")
        return -1

def download_image(xy, lon_ll, lat_ll, delta_lat, delta_lon, size_pixel_w, size_pixel_h, path_save, map_server, debug_level):
    """Download image from map server and save it."""
    global un_completed_tiles
    url, error_code = get_map_server(map_server, lat_ll, lon_ll, lat_ll + delta_lat, lon_ll + delta_lon, size_pixel_w, size_pixel_h)
    if error_code != 0:
        print(f"\nError: downloadImage - Map server error code: {error_code}")
        return False, None
    
    try:
        proxies = {"http": map_server.proxy, "https": map_server.proxy} if map_server.proxy else None
        response = requests.get(url, proxies=proxies, timeout=30)
        if response.status_code == 200:
            file_name = file_with_root_home_path(f"temp_{xy[6]}.png")
            with open(file_name, "wb") as f:
                f.write(response.content)
            quality = image_quality(file_name, debug_level)
            if quality > 0:
                return True, file_name
            else:
                if os.path.exists(file_name):
                    os.remove(file_name)
                if debug_level > 0:
                    print(f"downloadImage - Image quality check failed for {file_name}")
                return False, None
        else:
            if debug_level > 0:
                print(f"downloadImage - Failed to download image from {url}, status code: {response.status_code}")
            return False, None
    except Exception as err:
        if debug_level > 0:
            print(f"downloadImage - Error downloading image from {url}: {err}")
        return False, None


def convert_png_to_dds(png_file, dds_file, debug_level, converter="nvtt"):
    """Convert PNG to DDS using nvtt_export or ImageMagick based on converter choice."""
    try:
        start_time = time.time()
        
        if converter.lower() == "nvtt":
            nvtt_export_path = r"C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvtt_export.exe"
            if not os.path.exists(nvtt_export_path):
                raise FileNotFoundError(f"nvtt_export not found at {nvtt_export_path}")
            
            cmd = [nvtt_export_path, "--format", "bc3", "--output", dds_file, png_file]
            if debug_level > 0:
                print(f"Debug - convertPNGtoDDS: Running NVTT command: {' '.join(cmd)}")
            subprocess.check_call(cmd, stderr=subprocess.STDOUT)
            if debug_level > 0:
                print(f"convertPNGtoDDS - Successfully converted {png_file} to {dds_file} with NVTT in {time.time() - start_time:.2f} seconds")
            return True
        
        elif converter.lower() == "imagemagick":
            if os.name == 'nt':
                cmd = [
                    'magick', 'convert', png_file,
                    '-format', 'DDS',
                    '-define', 'dds:compression=dxt5',
                    '-define', 'dds:fast-mipmaps=true',
                    '-quality', '50',
                    dds_file
                ]
            else:
                cmd = [
                    'convert', png_file,
                    '-format', 'DDS',
                    '-define', 'dds:compression=dxt5',
                    '-define', 'dds:fast-mipmaps=true',
                    '-quality', '50',
                    dds_file
                ]
            if debug_level > 0:
                print(f"Debug - convertPNGtoDDS: Running ImageMagick command: {' '.join(cmd)}")
            subprocess.check_call(cmd)
            if debug_level > 0:
                print(f"convertPNGtoDDS - Successfully converted {png_file} to {dds_file} with ImageMagick in {time.time() - start_time:.2f} seconds")
            return True
        
        else:
            raise ValueError(f"Invalid converter specified: {converter}. Use 'nvtt' or 'imagemagick'.")
    
    except FileNotFoundError as e:
        if debug_level > 0:
            print(f"convertPNGtoDDS - Error: {e}. Please ensure {'NVIDIA Texture Tools Exporter' if converter.lower() == 'nvtt' else 'ImageMagick'} is installed.")
        return False
    except subprocess.CalledProcessError as e:
        if debug_level > 0:
            print(f"convertPNGtoDDS - Error converting {png_file} to DDS with {converter}: {e.output.decode() if e.output else str(e)}")
        return False
    except Exception as e:
        if debug_level > 0:
            print(f"convertPNGtoDDS - Unexpected error converting {png_file} to DDS with {converter}: {str(e)}")
        return False

def process_tile(xy, path_save, map_server, size, format, debug_level, converter="nvtt"):
    """Process a single tile by downloading sub-images in parallel and creating a mosaic."""
    try:
        tile_id = xy[6]
        lon_ll, lon_ur, lat_ur, lat_ll = xy[2], xy[3], xy[4], xy[5]
        size_pixel_w, cols_by_distance, size_pixel_h, grid_size = xy[11], xy[12], xy[13], xy[14]
        
        tile_dir = os.path.join(path_save, "Orthophotos", xy[0], xy[1])
        os.makedirs(tile_dir, exist_ok=True)
        temp_png = os.path.join(path_save, f"temp_{tile_id}.png")
        output_file = os.path.join(tile_dir, f"{tile_id}.{'dds' if format == 1 else 'png'}")
        
        if os.path.exists(output_file):
            if debug_level > 0:
                print(f"process_tile - Skipping existing tile: {output_file}")
            return True
        
        # Calculate dimensions of sub-images
        sub_width = 2048
        sub_height = 2048 if abs(lat_ll) <= 22.5 else 1024
        lon_step = (lon_ur - lon_ll) / grid_size
        lat_step = (lat_ur - lat_ll) / grid_size
        
        # Prepare list of sub-images and their URLs
        sub_images_info = []
        for i in range(grid_size):
            for j in range(grid_size):
                sub_lon_ll = lon_ll + j * lon_step
                sub_lon_ur = sub_lon_ll + lon_step
                sub_lat_ur = lat_ur - i * lat_step
                sub_lat_ll = sub_lat_ur - lat_step
                sub_png = os.path.join(path_save, f"temp_{tile_id}_{i}_{j}.png")
                url, error_code = get_map_server(map_server, sub_lat_ll, sub_lon_ll, sub_lat_ur, sub_lon_ur, sub_width, sub_height)
                if error_code != 0:
                    if debug_level > 0:
                        print(f"process_tile - Failed to construct URL for sub-tile {tile_id}_{i}_{j}: Error code {error_code}")
                    return False
                sub_images_info.append((sub_png, url, tile_id, i, j))
        
        # Auxiliary function to download a sub-image
        def download_sub_image(sub_info):
            sub_png, url, tile_id, i, j = sub_info
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with requests.get(url, stream=True, timeout=60, proxies={"http": map_server.proxy, "https": map_server.proxy} if map_server.proxy else None) as response:
                        response.raise_for_status()
                        with open(sub_png, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                    
                    if image_quality(sub_png, debug_level) > 0:
                        if debug_level > 0:
                            success, width, height = get_png_size(sub_png)
                            print(f"Debug - process_tile: Downloaded sub-tile {sub_png}, dimensions={width}x{height}")
                        return sub_png
                    else:
                        os.remove(sub_png)
                        return None
                except requests.exceptions.Timeout:
                    if debug_level > 0:
                        print(f"process_tile - Timeout downloading sub-tile {tile_id}_{i}_{j} (attempt {attempt + 1}/{max_retries})")
                    if attempt == max_retries - 1:
                        os.remove(sub_png) if os.path.exists(sub_png) else None
                        return None
                    time.sleep(2)
                except requests.exceptions.RequestException as err:
                    if debug_level > 0:
                        print(f"process_tile - Error downloading sub-tile {tile_id}_{i}_{j}: {err}")
                    os.remove(sub_png) if os.path.exists(sub_png) else None
                    return None
            return None
        
        # Download subimages in parallel
        sub_images = []
        if debug_level > 0:
            print(f"process_tile - Downloading {grid_size}x{grid_size} sub-images for tile {tile_id} in parallel")
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = [executor.submit(download_sub_image, sub_info) for sub_info in sub_images_info]
            for future in futures:
                result = future.result()
                if result:
                    sub_images.append(result)
                else:
                    for sub_img in sub_images:
                        os.remove(sub_img) if os.path.exists(sub_img) else None
                    return False
        
        if len(sub_images) != grid_size * grid_size:
            if debug_level > 0:
                print(f"process_tile - Failed to download all {grid_size}x{grid_size} sub-images for tile {tile_id}")
            for sub_img in sub_images:
                os.remove(sub_img) if os.path.exists(sub_img) else None
            return False
        
        # Create mosaic with ImageMagick
        try:
            if debug_level > 0:
                print(f"process_tile - Creating mosaic for tile {tile_id} with {grid_size}x{grid_size} sub-images")
            cmd = ['magick', 'montage'] + sub_images + ['-geometry', f'{sub_width}x{sub_height}+0+0', '-tile', f'{grid_size}x{grid_size}', temp_png]
            if debug_level > 0:
                print(f"Debug - process_tile: Running command: {' '.join(cmd)}")
            subprocess.check_call(cmd)
            
            # Check mosaic dimensions
            success, width, height = get_png_size(temp_png)
            if debug_level > 0:
                print(f"Debug - process_tile: Mosaic PNG {temp_png}, dimensions={width}x{height}")
            
            if success and width == size_pixel_w and height == size_pixel_h:
                if format == 1:
                    if convert_png_to_dds(temp_png, output_file, debug_level, converter=converter):
                        if debug_level > 0:
                            success, width, height = get_dds_size(output_file)
                            print(f"Debug - process_tile: Saved DDS {output_file}, dimensions={width}x{height}")
                        os.remove(temp_png)
                        for sub_img in sub_images:
                            os.remove(sub_img) if os.path.exists(sub_img) else None
                        return True
                    else:
                        os.remove(temp_png)
                        for sub_img in sub_images:
                            os.remove(sub_img) if os.path.exists(sub_img) else None
                        return False
                else:
                    shutil.move(temp_png, output_file)
                    if debug_level > 0:
                        success, width, height = get_png_size(output_file)
                        print(f"Debug - process_tile: Saved PNG {output_file}, dimensions={width}x{height}")
                    for sub_img in sub_images:
                        os.remove(sub_img) if os.path.exists(sub_img) else None
                    return True
            else:
                if debug_level > 0:
                    print(f"process_tile - Mosaic dimensions incorrect: expected {size_pixel_w}x{size_pixel_h}, got {width}x{height}")
                os.remove(temp_png) if os.path.exists(temp_png) else None
                for sub_img in sub_images:
                    os.remove(sub_img) if os.path.exists(sub_img) else None
                return False
        except subprocess.CalledProcessError as e:
            if debug_level > 0:
                print(f"process_tile - Error creating mosaic for tile {tile_id}: {e}")
            os.remove(temp_png) if os.path.exists(temp_png) else None
            for sub_img in sub_images:
                os.remove(sub_img) if os.path.exists(sub_img) else None
            return False
    except Exception as err:
        if debug_level > 0:
            print(f"process_tile - Error processing tile {tile_id}: {err}")
        os.remove(temp_png) if os.path.exists(temp_png) else None
        for sub_img in sub_images:
            os.remove(sub_img) if os.path.exists(sub_img) else None
        return False

def process_tiles(coordinates_matrix, map_coordinates, path_save, map_server, size, size_dwn, format, position_route, un_completed_tiles_attemps, debug_level, converter="nvtt"):
    """Process tiles in parallel using ThreadPoolExecutor, prioritizing the first tile."""
    global un_completed_tiles
    number_of_tiles = 0
    processed_tiles = 0
    cursor = display_cursor_type_a()
    
    # Process the first (closest) tile immediately
    if coordinates_matrix:
        first_tile_group = coordinates_matrix[0]
        first_xy = first_tile_group[0]
        tile_id = first_xy[6]
        dds_file = os.path.join(path_save, "Orthophotos", first_xy[0], first_xy[1], f"{tile_id}.dds")
        if os.path.exists(dds_file):
            if debug_level > 0:
                print(f"process_tiles - Skipping existing tile: {dds_file}")
            processed_tiles += 1
            number_of_tiles += 1
        else:
            number_of_tiles += 1
            size_pixel_w, size_pixel_h, cols_by_distance, grid_size = get_size_pixel_width_by_distance(size, size_dwn, map_coordinates.radius, first_xy[10], position_route, un_completed_tiles_attemps, lat=first_xy[5], debug_level=debug_level)
            first_tile_group[0] = first_xy[:-4] + (size_pixel_w, cols_by_distance, size_pixel_h, grid_size)
            if process_tile(first_tile_group[0], path_save, map_server, size, format, debug_level, converter=converter):
                processed_tiles += 1
            if debug_level > 0:
                print(f"process_tiles - Prioritized tile {tile_id} processed, size={size_pixel_w}x{size_pixel_h}, grid={grid_size}x{grid_size}")
    
    # Process the remaining tiles in parallel
    with ThreadPoolExecutor() as executor:
        for tile_group in coordinates_matrix[1:]:  # Skip the first group, already processed
            futures = []
            for i in range(0, len(tile_group), 2):
                xy = tile_group[i]
                tile_id = xy[6]
                dds_file = os.path.join(path_save, "Orthophotos", xy[0], xy[1], f"{tile_id}.dds")
                if os.path.exists(dds_file):
                    if debug_level > 0:
                        print(f"process_tiles - Skipping existing tile: {dds_file}")
                    processed_tiles += 1
                    number_of_tiles += 1
                    continue
                number_of_tiles += 1
                size_pixel_w, size_pixel_h, cols_by_distance, grid_size = get_size_pixel_width_by_distance(size, size_dwn, map_coordinates.radius, xy[10], position_route, un_completed_tiles_attemps, lat=xy[5], debug_level=debug_level)
                tile_group[i] = xy[:-4] + (size_pixel_w, cols_by_distance, size_pixel_h, grid_size)
                futures.append(executor.submit(process_tile, tile_group[i], path_save, map_server, size, format, debug_level, converter=converter))
            
            for future in futures:
                if future.result():
                    processed_tiles += 1
                if debug_level > 0:
                    print(f"\rProcessing tiles: {processed_tiles}/{number_of_tiles} {cursor()}", end="")
    
    if debug_level > 0:
        print(f"\nProcessed {processed_tiles} of {number_of_tiles} tiles")
    return processed_tiles, number_of_tiles

def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description="Photoscenery generator")
    parser.add_argument("-p", "--proxy", type=str, help="Proxy server (e.g., http://proxy:port)")
    parser.add_argument("-r", "--radius", type=float, default=10.0, help="Radius in nautical miles")
    parser.add_argument("-c", "--center", type=str, help="Center point (ICAO code or lat,lon)")
    parser.add_argument("-b", "--bbox", type=str, help="Bounding box (latLL,lonLL,latUR,lonUR)")
    parser.add_argument("-s", "--size", type=int, default=2, choices=range(6), help="Tile size (0=512, 1=1024, 2=2048, 3=4096, 4=8192, 5=16384)")
    parser.add_argument("-d", "--size_dwn", type=int, default=0, choices=range(6), help="Minimum tile size")
    parser.add_argument("-f", "--format", type=int, default=1, choices=[0, 1], help="Output format (0=PNG, 1=DDS)")
    parser.add_argument("-m", "--map_server", type=int, default=1, help="Map server ID")
    parser.add_argument("-o", "--output", type=str, default="C:\\Users\\Pc\\Documents\\Photoscenery", help="Output directory")
    parser.add_argument("-i", "--ip_port", type=str, default="127.0.0.1:5000", help="FlightGear Telnet IP:port")
    parser.add_argument("-t", "--route", type=str, help="Route file (FGFS or GPX)")
    parser.add_argument("-v", "--debug", type=int, default=0, help="Debug level (0-2)")
    parser.add_argument("--converter", type=str, default="nvtt", choices=["nvtt", "imagemagick"], help="Converter for DDS (nvtt or imagemagick)")
    args = parser.parse_args()

    image_magick_path = initialize()
    is_image_magick_ok, image_magick_path = check_image_magick(image_magick_path)
    if not is_image_magick_ok:
        print("Error: ImageMagick is not operational")
        sys.exit(1)

    map_server = MapServer(args.map_server, args.proxy)
    if map_server.error_code != 0:
        print(f"\nError: Map server configuration error, code: {map_server.error_code}")
        if args.debug > 0:
            print(f"MapServer - web_url_base: {getattr(map_server, 'web_url_base', 'None')}, web_url_command: {getattr(map_server, 'web_url_command', 'None')}, name: {getattr(map_server, 'name', 'None')}")
        sys.exit(1)
    if args.debug > 0:
        print(f"MapServer - Initialized with web_url_base: {map_server.web_url_base}, web_url_command: {map_server.web_url_command}, name: {map_server.name}")

    path_save = os.path.normpath(args.output)
    orthophotos_dir = os.path.join(path_save, "Orthophotos")
    os.makedirs(orthophotos_dir, exist_ok=True)
    if args.debug > 0:
        print(f"main - Output directory set to: {orthophotos_dir}")

    while True:
        coordinates_matrix = None
        number_of_tiles = 0
        position_route = None
        map_coordinates = None

        if args.route:
            route_list, route_size = load_route(args.route, args.radius)
            if route_size > 0:
                position_route = FGFSPositionRoute(args.radius, 0.5)
                position_route.marks = [(lat, lon, 0.0) for lat, lon, _ in route_list]
                position_route.size = route_size
                map_coordinates = MapCoordinates(route_list[0][0], route_list[0][1], args.radius)
                coordinates_matrix, number_of_tiles, map_coordinates = coordinate_matrix_generator(
                    map_coordinates, None, args.size, args.size_dwn, 0, position_route, args.debug
                )
        elif args.center:
            if "," in args.center:
                lat, lon = map(float, args.center.split(","))
                map_coordinates = MapCoordinates(lat, lon, args.radius)
                coordinates_matrix, number_of_tiles, map_coordinates = coordinate_matrix_generator(
                    map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
                )
            else:
                lat, lon, error_code = select_icao(args.center, args.radius)
                if error_code == 0:
                    map_coordinates = MapCoordinates(lat, lon, args.radius)
                    coordinates_matrix, number_of_tiles, map_coordinates = coordinate_matrix_generator(
                        map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
                    )
                else:
                    sys.exit(1)
        elif args.bbox:
            lat_ll, lon_ll, lat_ur, lon_ur = map(float, args.bbox.split(","))
            map_coordinates = MapCoordinates(0, 0, None, lat_ll, lon_ll, lat_ur, lon_ur)
            coordinates_matrix, number_of_tiles, map_coordinates = coordinate_matrix_generator(
                map_coordinates, None, args.size, args.size_dwn, 0, None, args.debug
            )
        else:
            lat = get_fgfs_position_lat(args.ip_port, args.debug)
            lon = get_fgfs_position_lon(args.ip_port, args.debug)
            if lat is not None and lon is not None:
                position_route = get_fgfs_position_set_task(args.ip_port, args.radius, 0.5, args.debug)
                map_coordinates = MapCoordinates(lat, lon, args.radius)
                coordinates_matrix, number_of_tiles, map_coordinates = coordinate_matrix_generator(
                    map_coordinates, None, args.size, args.size_dwn, 0, position_route, args.debug
                )
            else:
                print("\nError: Could not retrieve position from FlightGear")
                time.sleep(5)
                continue

        if coordinates_matrix:
            processed_tiles, total_tiles = process_tiles(
                coordinates_matrix, map_coordinates, path_save, map_server, args.size, args.size_dwn, args.format, position_route, 0, args.debug, converter=args.converter
            )
            print(f"\nCompleted processing {processed_tiles} of {total_tiles} tiles")
        else:
            print("\nError: Failed to generate coordinate matrix")
            time.sleep(5)
            continue

        time.sleep(10)
if __name__ == "__main__":
    main()