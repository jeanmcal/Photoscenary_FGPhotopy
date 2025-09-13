# License: GPL 2

import os
import subprocess
import csv
import math
import json
import signal
import shutil
import webview
from flask import Flask, request, jsonify, render_template

app = Flask(__name__, static_folder='./static', template_folder='./templates')
script_dir = os.path.dirname(os.path.abspath(__file__))
html_file_path = os.path.join(script_dir, 'index.html')

# Configuration file path
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')
DEFAULT_OUTPUT_PATH = r"C:\Users\Pc\Documents\Photoscenery"  # Default output directory

current_process = None  # Tracks the current subprocess for downloads

def validate_path(path: str) -> tuple[bool, str | None]:
    """Validate if a path exists or can be created and is writable."""
    try:
        normalized_path = os.path.normpath(path)
        if not normalized_path:
            return False, "Output path cannot be empty."
        parent_dir = os.path.dirname(normalized_path) or normalized_path
        os.makedirs(parent_dir, exist_ok=True)
        if not os.access(parent_dir, os.W_OK):
            return False, f"Directory {parent_dir} is not writable."
        return True, None
    except Exception as e:
        return False, f"Error validating path {path}: {str(e)}"

def calculate_tile_coordinates(tile_index: int) -> tuple[float, float, float, float, int, int, float, float]:
    """Convert a FlightGear tile index to coordinates and parameters."""
    lon = (tile_index >> 14) - 180
    lat = ((tile_index - ((lon + 180) << 14)) >> 6) - 90
    y_val = (tile_index - (((lon + 180) << 14) + ((lat + 90) << 6))) >> 3
    x_val = tile_index - ((((lon + 180) << 14) + ((lat + 90) << 6)) + (y_val << 3))
    tile_width_deg = get_tile_width(lat)
    center_lon = lon + (x_val + 0.5) * tile_width_deg
    center_lat = lat + (y_val + 0.5) * 0.125
    return center_lon, center_lat, lon, lat, x_val, y_val, tile_width_deg, 0.125

def get_tile_width(latitude: float) -> float:
    """Return tile width in degrees based on latitude for FlightGear."""
    abs_lat = abs(float(latitude))
    if abs_lat >= 89.0:
        return 12.0
    if abs_lat >= 86.0:
        return 4.0
    if abs_lat >= 83.0:
        return 2.0
    if abs_lat >= 76.0:
        return 1.0
    if abs_lat >= 62.0:
        return 0.5
    if abs_lat > 22.0:
        return 0.25
    return 0.125

def load_airports(file_path: str = "airports.csv") -> list[dict]:
    """Load airports from a CSV file, filtering by type."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            airports = [
                {
                    'icao': row['ident'],
                    'lat': float(row['latitude_deg']),
                    'lon': float(row['longitude_deg']),
                    'name': row.get('name', 'Unknown')
                }
                for row in reader
                if row['type'] in ['small_airport', 'medium_airport', 'large_airport']
            ]
        print(f"Loaded {len(airports)} airports from {file_path}")
        return airports
    except FileNotFoundError:
        print(f"Error: File {file_path} not found. Using static list for testing.")
        return [
            {'icao': "SBGL", 'lat': -22.8089, 'lon': -43.2436, 'name': "Galeão - Antônio Carlos Jobim"},
            {'icao': "SBRJ", 'lat': -22.9105, 'lon': -43.1719, 'name': "Santos Dumont"}
        ]
    except Exception as e:
        print(f"Error loading airports.csv: {e}")
        return []

def tile_contains_airport(latitude: float, longitude: float, airports: list[dict]) -> bool:
    """Check if a tile contains any airports within its bounds."""
    if math.isnan(latitude) or math.isnan(longitude):
        print(f"Error: Invalid coordinates (lat={latitude}, lon={longitude})")
        return False
    tile_bounds = {
        'lat_min': latitude,
        'lat_max': latitude + 1.0,
        'lon_min': longitude,
        'lon_max': longitude + 1.0
    }
    print(f"Checking tile for airports: lat={latitude}, lon={longitude}, bounds=[{tile_bounds['lat_min']:.3f}, {tile_bounds['lat_max']:.3f}, {tile_bounds['lon_min']:.3f}, {tile_bounds['lon_max']:.3f}]")
    for airport in airports:
        if (tile_bounds['lat_min'] <= airport['lat'] < tile_bounds['lat_max'] and
                tile_bounds['lon_min'] <= airport['lon'] < tile_bounds['lon_max']):
            print(f"Airport found: {airport['icao']} at lat={airport['lat']}, lon={airport['lon']}")
            return True
    print(f"No airports found for tile lat={latitude}, lon={longitude}")
    return False

def generate_folder_name(latitude: float, longitude: float, silent: bool = False) -> str:
    """Generate folder name based on latitude and longitude."""
    lon_prefix = 'e' if longitude >= 0 else 'w'
    lat_prefix = 'n' if latitude >= 0 else 's'
    folder_name = f"{lon_prefix}{abs(int(longitude)):03d}{lat_prefix}{abs(int(latitude)):02d}"
    if not silent:
        print(f"Generated folder_name={folder_name} for lat={latitude}, lon={longitude}")
    return folder_name

def parse_tile_name(tile: str, silent: bool = False) -> tuple[float | None, float | None]:
    """Parse a tile name to extract latitude and longitude."""
    try:
        parts = tile.split('-')
        if not silent:
            print(f"Parsing tile: {tile}, parts: {parts}")
        if parts[0] == '':
            latitude = float('-' + parts[1])
            longitude = float('-' + (parts[3] if len(parts) > 3 else parts[2]))
        else:
            latitude = float(parts[0])
            longitude = float('-' + parts[2]) if len(parts) > 2 and parts[1] == '' else float(parts[1])
        if not silent:
            print(f"Parsed tile {tile}: lat={latitude}, lon={longitude}")
        return latitude, longitude
    except (IndexError, ValueError) as e:
        if not silent:
            print(f"Error parsing tile {tile}: {e}")
        return None, None

def validate_subtiles(folder_path: str, latitude: float, longitude: float) -> int:
    """Validate and remove sub-tiles outside the tile's bounding box."""
    tile_bounds = {
        'lat_min': latitude,
        'lat_max': latitude + 1.0,
        'lon_min': longitude,
        'lon_max': longitude + 1.0
    }
    valid_files = []
    invalid_files = []

    try:
        os.makedirs(folder_path, exist_ok=True)
        print(f"Created/verified directory: {folder_path}")
    except Exception as e:
        print(f"Error creating directory {folder_path}: {str(e)}")
        return 0

    if os.path.exists(folder_path):
        for file in os.listdir(folder_path):
            if file.endswith('.dds'):
                try:
                    tile_id = int(file.split('.')[0])
                    center_lon, center_lat, tile_lon_deg, tile_lat_deg, x_val, y_val, _, _ = calculate_tile_coordinates(tile_id)
                    tile_width_deg = get_tile_width(tile_lat_deg)
                    subtile_bounds = {
                        'min_lon': tile_lon_deg + x_val * tile_width_deg,
                        'max_lon': tile_lon_deg + (x_val + 1) * tile_width_deg,
                        'min_lat': tile_lat_deg + y_val * 0.125,
                        'max_lat': tile_lat_deg + (y_val + 1) * 0.125
                    }
                    if (tile_bounds['lat_min'] <= subtile_bounds['min_lat'] < tile_bounds['lat_max'] and
                            tile_bounds['lon_min'] <= subtile_bounds['min_lon'] < tile_bounds['lon_max']):
                        valid_files.append(file)
                        print(f"Valid subtile: {file}, bounds=[{subtile_bounds['min_lat']:.3f}, {subtile_bounds['max_lat']:.3f}, {subtile_bounds['min_lon']:.3f}, {subtile_bounds['max_lon']:.3f}]")
                    else:
                        invalid_files.append(file)
                        print(f"Invalid subtile: {file}, bounds=[{subtile_bounds['min_lat']:.3f}, {subtile_bounds['max_lat']:.3f}, {subtile_bounds['min_lon']:.3f}, {subtile_bounds['max_lon']:.3f}]")
                except ValueError:
                    continue
        for file in invalid_files:
            try:
                os.remove(os.path.join(folder_path, file))
                print(f"Removed invalid subtile: {file}")
            except Exception as e:
                print(f"Error removing {file}: {e}")
    else:
        print(f"Directory not found: {folder_path}")
    return len(valid_files)

airports = load_airports()

@app.route('/')
def index():
    """Render the main application page."""
    return render_template('index.html')

def load_config() -> dict:
    """Load configuration from config.json or return default values."""
    default_config = {
        'output_path': DEFAULT_OUTPUT_PATH,
        'quality_terrain': '2',
        'map_center': {'lat': -19, 'lng': -45},
        'map_zoom': 10,
        'converter': 'imagemagick',
        'show_airports': True  # Default to True to match HTML checkbox
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as file:
                config = json.load(file)
                for key, value in default_config.items():
                    config.setdefault(key, value)
                return config
        return default_config
    except Exception as e:
        print(f"Error loading config.json: {e}")
        return default_config

def save_config(config: dict) -> None:
    """Save configuration to config.json."""
    try:
        with open(CONFIG_FILE, 'w') as file:
            json.dump(config, file, indent=4)
        print(f"Configuration saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"Error saving config.json: {e}")

@app.route('/api/load_config', methods=['GET'])
def load_config_route():
    """Return the current configuration."""
    return jsonify(load_config())

@app.route('/api/save_config', methods=['POST'])
def save_config_route():
    """Save the provided configuration."""
    try:
        config = request.json
        save_config(config)
        return jsonify({'status': 'success', 'message': 'Configuration saved successfully'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error saving configuration: {str(e)}'}), 500

@app.route('/api/airports', methods=['GET'])
def get_airports():
    """Return airports within the specified bounding box or all airports."""
    try:
        bbox = request.args.get('bbox')
        if bbox:
            lat_min, lon_min, lat_max, lon_max = map(float, bbox.split(','))
            filtered_airports = [
                airport for airport in airports
                if lat_min <= airport['lat'] <= lat_max and lon_min <= airport['lon'] <= lon_max
            ]
            print(f"Sending {len(filtered_airports)} airports within bbox {bbox}")
            return jsonify(filtered_airports)
        print(f"Sending {len(airports)} global airports")
        return jsonify(airports)
    except Exception as e:
        print(f"Error in /api/airports: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/check_tiles', methods=['POST'])
def check_tiles():
    """Check the existence of tiles and subtiles in the output directory."""
    try:
        data = request.json
        if not data or 'tiles' not in data:
            print("Error: Invalid data received in /api/check_tiles")
            return jsonify({'status': 'error', 'message': 'Invalid data or tiles not provided'}), 400

        tiles = data.get('tiles', [])
        silent = data.get('silent', False)
        check_level = data.get('check_level', 'file')
        output_path = data.get('output_path', DEFAULT_OUTPUT_PATH)

        is_valid, error_message = validate_path(output_path)
        if not is_valid:
            print(f"Error: {error_message}")
            return jsonify({'status': 'error', 'message': error_message}), 400

        orthophotos_path = os.path.join(output_path, 'Orthophotos')
        folder_status = {}
        for tile in tiles:
            latitude, longitude = parse_tile_name(tile, silent=silent)
            if latitude is None or longitude is None:
                folder_status[tile] = {'found': False, 'dds_files': []}
                if not silent:
                    print(f"Checking tile {tile}: Invalid coordinates")
                continue
            folder_name = generate_folder_name(latitude, longitude, silent=silent)
            folder_path = find_folder_path(orthophotos_path, folder_name)

            if check_level == 'folder':
                folder_status[tile] = {
                    'found': folder_path is not None,
                    'dds_files': []
                }
                if not silent:
                    print(f"Checking tile {tile} ({folder_name}): {'Found' if folder_path else 'Not found'}")
            else:
                dds_files = []
                if folder_path:
                    for root, _, files in os.walk(folder_path):
                        for file in files:
                            if file.endswith('.dds'):
                                try:
                                    tile_id = int(file.split('.')[0])
                                    center_lon, center_lat, tile_lon_deg, tile_lat_deg, x_val, y_val, _, _ = calculate_tile_coordinates(tile_id)
                                    tile_width_deg = get_tile_width(tile_lat_deg)
                                    dds_info = {
                                        'tile_id': tile_id,
                                        'min_lat': tile_lat_deg + y_val * 0.125,
                                        'max_lat': tile_lat_deg + (y_val + 1) * 0.125,
                                        'min_lon': tile_lon_deg + x_val * tile_width_deg,
                                        'max_lon': tile_lon_deg + (x_val + 1) * tile_width_deg
                                    }
                                    dds_files.append(dds_info)
                                    if not silent:
                                        print(f"Found: {os.path.join(root, file)}")
                                except ValueError:
                                    continue
                folder_status[tile] = {
                    'found': len(dds_files) > 0,
                    'dds_files': dds_files
                }
                if not silent:
                    print(f"Checking tile {tile} ({folder_name}): {'Found' if dds_files else 'Not found'}")
        return jsonify(folder_status)
    except Exception as e:
        print(f"Error in /api/check_tiles: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

def find_folder_path(base_path: str, folder_name: str) -> str | None:
    """Find the folder path matching the folder name."""
    for root, dirs, _ in os.walk(base_path):
        if folder_name in dirs:
            possible_path = os.path.join(root, folder_name)
            if os.path.basename(os.path.dirname(possible_path)).startswith(('w', 'e')):
                return possible_path
    return None

def calculate_tile_id(latitude: float, longitude: float, row: int, col: int) -> int:
    """Calculate FlightGear tile index for a subtile at position (row, col)."""
    lon_base = int(math.floor(longitude))
    lat_base = int(math.floor(latitude))
    lon_idx = lon_base + 180
    lat_idx = lat_base + 90
    return (lon_idx << 14) + (lat_idx << 6) + (row << 3) + col

@app.route('/api/remove_tiles', methods=['POST'])
def remove_tiles():
    """Remove specified tiles or subtiles from the output directory."""
    try:
        data = request.json
        tiles = data.get('tiles', [])
        subtiles = data.get('subtiles', [])
        output_path = data.get('output_path', DEFAULT_OUTPUT_PATH)

        is_valid, error_message = validate_path(output_path)
        if not is_valid:
            print(f"Error: {error_message}")
            return jsonify({'status': 'error', 'message': error_message, 'deleted': [], 'errors': [error_message]}), 400

        orthophotos_path = os.path.join(output_path, 'Orthophotos')
        deleted_items = []
        errors = []

        for tile in tiles:
            latitude, longitude = parse_tile_name(tile, silent=True)
            if latitude is None or longitude is None:
                errors.append(f"Invalid coordinates for tile {tile}")
                continue
            folder_name = generate_folder_name(latitude, longitude, silent=True)
            folder_path = find_folder_path(orthophotos_path, folder_name)
            if folder_path and os.path.exists(folder_path):
                try:
                    shutil.rmtree(folder_path)
                    deleted_items.append(f"Tile {tile} ({folder_name}) removed")
                    print(f"Removed tile {tile}: {folder_path}")
                except Exception as e:
                    errors.append(f"Error removing tile {tile}: {str(e)}")
                    print(f"Error removing tile {tile}: {str(e)}")
            else:
                errors.append(f"Directory not found for tile {tile}: {folder_path or 'unknown'}")
                print(f"Directory not found for tile {tile}: {folder_path or 'unknown'}")

        for subtile in subtiles:
            parent_tile = subtile.get('parent_tile')
            tile_id = subtile.get('tile_id')
            if not parent_tile or tile_id is None:
                errors.append(f"Invalid data for subtile: {subtile}")
                continue
            latitude, longitude = parse_tile_name(parent_tile, silent=True)
            if latitude is None or longitude is None:
                errors.append(f"Invalid coordinates for parent_tile {parent_tile}")
                continue
            folder_name = generate_folder_name(latitude, longitude, silent=True)
            folder_path = find_folder_path(orthophotos_path, folder_name)
            if folder_path and os.path.exists(folder_path):
                file_path = os.path.join(folder_path, f"{tile_id}.dds")
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        deleted_items.append(f"Subtile {tile_id}.dds removed from {folder_name}")
                        print(f"Removed subtile {tile_id}.dds from {folder_path}")
                    except Exception as e:
                        errors.append(f"Error removing subtile {tile_id}.dds: {str(e)}")
                        print(f"Error removing subtile {tile_id}.dds: {str(e)}")
                else:
                    errors.append(f"File not found for subtile {tile_id}.dds in {folder_path}")
                    print(f"File not found for subtile {tile_id}.dds in {folder_path}")
            else:
                errors.append(f"Directory not found for parent_tile {parent_tile}: {folder_path or 'unknown'}")
                print(f"Directory not found for parent_tile {parent_tile}: {folder_path or 'unknown'}")

        for subtile in subtiles:
            parent_tile = subtile.get('parent_tile')
            if parent_tile:
                latitude, longitude = parse_tile_name(parent_tile, silent=True)
                if latitude is not None and longitude is not None:
                    folder_name = generate_folder_name(latitude, longitude, silent=True)
                    folder_path = os.path.join(orthophotos_path, folder_name)
                    if os.path.exists(folder_path) and not os.listdir(folder_path):
                        try:
                            shutil.rmtree(folder_path)
                            deleted_items.append(f"Empty directory {folder_name} removed")
                            print(f"Empty directory {folder_name} removed")
                        except Exception as e:
                            errors.append(f"Error removing empty directory {folder_name}: {str(e)}")
                            print(f"Error removing empty directory {folder_name}: {str(e)}")

        return jsonify({
            'status': 'success' if not errors else 'partial',
            'deleted': deleted_items,
            'errors': errors
        })
    except Exception as e:
        print(f"Error in /api/remove_tiles: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e),
            'deleted': [],
            'errors': [str(e)]
        }), 500

@app.route('/api/download_tile', methods=['POST'])
def download_tile():
    """Download a 1x1 tile using the Photoscenary script."""
    global current_process
    try:
        data = request.json
        latitude = float(data.get('lat'))
        longitude = float(data.get('lon'))
        quality = data.get('quality_terrain', '2')
        converter = data.get('converter', 'imagemagick')
        output_path = data.get('output_path', DEFAULT_OUTPUT_PATH)

        is_valid, error_message = validate_path(output_path)
        if not is_valid:
            print(f"Error: {error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message,
                'tile': generate_folder_name(latitude, longitude, silent=True),
                'quality': 'unknown',
                'dds_count': 0
            }), 400

        tile_name = generate_folder_name(latitude, longitude)
        bbox = f"{latitude:.3f},{longitude:.3f},{latitude + 1.0:.3f},{longitude + 1.0:.3f}"
        has_airport = tile_contains_airport(latitude, longitude, airports)
        print(f"Selected quality for tile {tile_name}: {quality} (has_airport={has_airport})")
        print(f"BBox for download: {bbox}")

        cmd = [
            "python",
            "Photoscenary.py",
            "-o", output_path,
            f"--bbox={bbox}",
            "-r", "15",
            "-s", str(quality),
            "-f", "1",
            "--converter", converter,
            "-v", "2"
        ]

        print(f"Executing command for tile {tile_name}: {' '.join(cmd)}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        stdout, stderr = current_process.communicate()

        folder_path = os.path.join(output_path, 'Orthophotos', tile_name)
        dds_count = validate_subtiles(folder_path, latitude, longitude)
        print(f"Tile {tile_name}: Generated {dds_count} valid .dds files in {folder_path}")

        if current_process.returncode == 0:
            print(f"Command output for tile {tile_name}:\n{stdout}")
            if stderr:
                print(f"Warnings/Errors for tile {tile_name}:\n{stderr}")
            return jsonify({
                'status': 'success',
                'output': stdout,
                'tile': tile_name,
                'quality': quality,
                'dds_count': dds_count
            })
        else:
            error_message = f"Error executing command for tile {tile_name}: {stderr}"
            print(error_message)
            return jsonify({
                'status': 'error',
                'message': error_message,
                'tile': tile_name,
                'quality': quality,
                'dds_count': dds_count
            }), 500
    except (ValueError, TypeError, KeyError) as e:
        error_message = f"Error: Invalid coordinates received: lat={data.get('lat')}, lon={data.get('lon')}, error={str(e)}"
        print(error_message)
        return jsonify({
            'status': 'error',
            'message': error_message,
            'tile': locals().get('tile_name', 'unknown'),
            'quality': locals().get('quality', 'unknown'),
            'dds_count': 0
        }), 400
    except Exception as e:
        error_message = f"Unexpected error processing tile {locals().get('tile_name', 'unknown')}: {str(e)}"
        print(error_message)
        return jsonify({
            'status': 'error',
            'message': error_message,
            'tile': locals().get('tile_name', 'unknown'),
            'quality': locals().get('quality', 'unknown'),
            'dds_count': 0
        }), 500
    finally:
        current_process = None

@app.route('/api/download_subtile', methods=['POST'])
def download_subtile():
    """Download a subtile using the Photoscenary script."""
    global current_process
    try:
        data = request.json
        latitude = float(data.get('lat'))
        longitude = float(data.get('lon'))
        quality = data.get('quality', '2')
        converter = data.get('converter', 'imagemagick')
        output_path = data.get('output_path', DEFAULT_OUTPUT_PATH)
        parent_tile = data.get('parent_tile')
        parent_lat, parent_lon = parse_tile_name(parent_tile)

        is_valid, error_message = validate_path(output_path)
        if not is_valid:
            print(f"Error: {error_message}")
            return jsonify({
                'status': 'error',
                'message': error_message,
                'tile': 'unknown',
                'quality': quality,
                'dds_count': 0
            }), 400

        tile_width_deg = get_tile_width(latitude)
        lat_upper = latitude + 0.125
        lon_upper = longitude + tile_width_deg / 8
        tile_name = f"subtile_{latitude:.3f}_{longitude:.3f}"
        bbox = f"{latitude:.3f},{longitude:.3f},{lat_upper:.3f},{lon_upper:.3f}"

        print(f"Received: lat={latitude}, lon={longitude}, quality={quality}, parent_tile={parent_tile}, output_path={output_path}")
        print(f"BBox for subtile download: {bbox}")

        folder_path = os.path.join(output_path, 'Orthophotos', generate_folder_name(parent_lat, parent_lon))
        os.makedirs(folder_path, exist_ok=True)
        print(f"Created/verified directory: {folder_path}")

        cmd = [
            "python",
            "Photoscenary.py",
            "-o", output_path,
            f"--bbox={bbox}",
            "-r", "15",
            "-s", str(quality),
            "-f", "1",
            "--converter", converter,
            "-v", "2"
        ]

        print(f"Executing command for subtile {tile_name}: {' '.join(cmd)}")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        current_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env
        )
        stdout, stderr = current_process.communicate()

        dds_count = validate_subtiles(folder_path, parent_lat, parent_lon)
        print(f"Subtile {tile_name}: Generated {dds_count} valid .dds files in {folder_path}")

        if current_process.returncode == 0:
            print(f"Command output for subtile {tile_name}:\n{stdout}")
            if stderr:
                print(f"Warnings/Errors for subtile {tile_name}:\n{stderr}")
            return jsonify({
                'status': 'success',
                'output': stdout,
                'tile': tile_name,
                'quality': quality,
                'dds_count': dds_count
            })
        else:
            error_message = f"Error executing command for subtile {tile_name}: {stderr}"
            print(error_message)
            return jsonify({
                'status': 'error',
                'message': error_message,
                'tile': tile_name,
                'quality': quality,
                'dds_count': dds_count
            }), 500
    except (ValueError, TypeError, KeyError) as e:
        error_message = f"Error: Invalid coordinates received: lat={data.get('lat')}, lon={data.get('lon')}, error={str(e)}"
        print(error_message)
        return jsonify({
            'status': 'error',
            'message': error_message,
            'tile': locals().get('tile_name', 'unknown'),
            'quality': locals().get('quality', 'unknown'),
            'dds_count': 0
        }), 400
    except Exception as e:
        error_message = f"Unexpected error processing subtile {locals().get('tile_name', 'unknown')}: {str(e)}"
        print(error_message)
        return jsonify({
            'status': 'error',
            'message': error_message,
            'tile': locals().get('tile_name', 'unknown'),
            'quality': locals().get('quality', 'unknown'),
            'dds_count': 0
        }), 500
    finally:
        current_process = None

@app.route('/api/cancel_download', methods=['POST'])
def cancel_download():
    """Cancel an ongoing download process."""
    global current_process
    try:
        if current_process is not None:
            current_process.terminate()
            try:
                current_process.wait(timeout=5)
                print("Download process canceled successfully.")
            except subprocess.TimeoutExpired:
                current_process.kill()
                print("Download process forcefully terminated.")
            current_process = None
            return jsonify({'status': 'success', 'message': 'Download canceled'})
        print("No download process in progress.")
        return jsonify({'status': 'error', 'message': 'No download in progress'})
    except Exception as e:
        print(f"Error canceling download: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Commented out: Alternative entry point for running with webview, not used when running Flask directly
if __name__ == '__main__':
    webview.create_window('FGPhotopy', app)
    webview.start()

# If you want to use the Web version through an IDE or Python, uncomment the section below and comment out the section above.
#if __name__ == '__main__':
#   app.run(debug=True, threaded=True)
