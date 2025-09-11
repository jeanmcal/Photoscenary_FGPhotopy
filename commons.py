# License: GPL 2

import os
import math
from pathlib import Path
import subprocess
import stat
from scandir import walkdir
from wand.image import Image

# Constants
M = [90, 89, 86, 83, 76, 62, 22, -22]
N = [12.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125]

def tile_width(lat):
    """Return the tile width in degrees based on latitude, per FlightGear."""
    lat = abs(float(lat))
    if lat >= 89.0:
        return 12.0
    elif lat >= 86.0:
        return 4.0
    elif lat >= 83.0:
        return 2.0
    elif lat >= 76.0:
        return 1.0
    elif lat >= 62.0:
        return 0.5
    elif lat > 22.0:
        return 0.25
    else:
        return 0.125

def base_x(lat, lon):
    """Calculate base longitude for tile."""
    return math.floor(math.floor(lon / tile_width(lat)) * tile_width(lat))

def x(lat, lon):
    """Calculate x index for tile."""
    return math.floor((lon - base_x(lat, lon)) / tile_width(lat))

def base_y(lat):
    """Calculate base latitude for tile."""
    return math.floor(lat)

def y(lat):
    """Calculate y index for tile."""
    return math.floor((lat - base_y(lat)) * 8)

def index(lat, lon):
    """Calculate tile index from latitude and longitude."""
    return (math.floor(lon + 180) << 14) + (math.floor(lat + 90) << 6) + (y(lat) << 3) + x(lat, lon)

def min_lat(lat):
    """Calculate minimum latitude for tile."""
    return base_y(lat) + 1.0 * (y(lat) / 8)

def max_lat(lat):
    """Calculate maximum latitude for tile."""
    return base_y(lat) + 1.0 * ((1 + y(lat)) / 8)

def min_lon(lat, lon):
    """Calculate minimum longitude for tile."""
    return base_x(lat, lon) + x(lat, lon) * tile_width(lat)

def max_lon(lat, lon):
    """Calculate maximum longitude for tile."""
    return min_lon(lat, lon) + tile_width(lat)

def center_lat(lat):
    """Calculate center latitude for tile."""
    return min_lat(lat) + (max_lat(lat) - min_lat(lat)) / 2.0

def center_lon(lat, lon):
    """Calculate center longitude for tile."""
    return min_lon(lat, lon) + (max_lon(lat, lon) - min_lon(lat, lon)) / 2.0

def long_deg_on_latitude_nm(lat):
    """Calculate longitudinal degree distance in nautical miles."""
    return 2 * math.pi * 6371.0 * 0.53996 * math.cos(math.radians(lat)) / 360.0

def long_deg_on_longitude_nm():
    """Calculate latitudinal degree distance in nautical miles."""
    return math.pi * 6378.0 * 0.53996 / 180.0

def lat_deg_by_central_point(lat, lon, radius):
    """Calculate bounding box coordinates based on central point and radius."""
    return (
        round((lat - (lat % 0.125)) - (radius / long_deg_on_longitude_nm()), 1),
        round((lon - (lon % tile_width(lat))) - (radius / long_deg_on_latitude_nm(lat)), 1),
        round((lat - (lat % 0.125) + 0.125) + (radius / long_deg_on_longitude_nm()), 1),
        round((lon - (lon % tile_width(lat)) + tile_width(lat)) + (radius / long_deg_on_latitude_nm(lat)), 1)
    )

def size_height(size_width, lat):
    """Calculate image height based on width and latitude."""
    return int(size_width / (8 * tile_width(lat)))

def in_value(value, extrem):
    """Check if value is within extrem bounds."""
    return abs(value) <= extrem

def coord_from_index(index):
    """Convert tile index to coordinates and identifiers."""
    lon = (index >> 14) - 180
    lat = ((index - ((lon + 180) << 14)) >> 6) - 90
    y_val = (index - (((lon + 180) << 14) + ((lat + 90) << 6))) >> 3
    x_val = index - (((lon + 180) << 14) + ((lat + 90) << 6) + (y_val << 3))
    a = (
        ("e" if lon >= 0.0 else "w") +
        f"{int(math.floor(abs(lon)) if lon >= 0.0 else math.ceil(abs(lon))):03d}" +
        ("n" if lat >= 0.0 else "s") +
        f"{int(math.floor(abs(lat)) if lat >= 0.0 else math.ceil(abs(lat))):02d}"
    )
    b = (
        ("e" if lon >= 0.0 else "w") +
        f"{int(math.floor(abs(lon)) if lon >= 0.0 else math.ceil(abs(lon))):03d}" +
        ("n" if lat >= 0.0 else "s") +
        f"{int(math.floor(abs(lat)) if lat >= 0.0 else math.ceil(abs(lat))):02d}"
    )
    return (
        lon + (tile_width(lat) / 2.0 + x_val * tile_width(lat)) / 2.0,
        lat + (0.125 / 2 + y_val * 0.125) / 2.0,
        lon, lat, x_val, y_val, a, b
    )

def count_dir_error():
    """Track directory errors."""
    dirs_with_errors = 0

    def add(err):
        nonlocal dirs_with_errors
        dirs_with_errors += 1

    def get():
        nonlocal dirs_with_errors
        return dirs_with_errors

    return add, get

def find_file(file_name, path=None):
    """Find files matching the given name in the specified path."""
    if path is None:
        if len(os.path.dirname(file_name)) > 0:
            path = os.path.dirname(file_name)
            file_name = os.path.basename(file_name)
        else:
            if not os.path.isfile(file_name):
                path = os.path.expanduser("~")
                file_name = os.path.basename(file_name)
            else:
                path = os.getcwd()

    files_path = []
    full_path = os.path.join(path, file_name)
    if os.path.isfile(full_path):
        files_path.append((1, full_path, os.path.getmtime(full_path), os.path.getsize(full_path)))
    else:
        cde_add, cde_get = count_dir_error()
        id_counter = 0
        for root, dirs, files in walkdir(path, onerror=cde_add):
            for file in files:
                if file == file_name:
                    id_counter += 1
                    file_path = os.path.join(root, file)
                    files_path.append((id_counter, file_path, os.path.getmtime(file_path), os.path.getsize(file_path)))
    return files_path

def get_file_extension(filename):
    """Get the file extension."""
    return os.path.splitext(filename)[1] or None

def get_file_name(filename):
    """Get the file name without extension."""
    return os.path.splitext(filename)[0] or None

def get_dds_size(image_with_path_type_dds):
    """Get dimensions of a DDS image using ImageMagick."""
    if os.path.isfile(image_with_path_type_dds):
        try:
            if os.name == 'nt':
                identify = subprocess.check_output(['magick', 'identify', image_with_path_type_dds], text=True)
            else:
                identify = subprocess.check_output(['identify', image_with_path_type_dds], text=True)
            dimensions = identify.split(" ")[2].split("x")
            return True, int(dimensions[0]), int(dimensions[1])
        except Exception:
            return False, 0, 0
    return False, 0, 0

def get_png_size(image_with_path_type_png):
    """Get dimensions of a PNG image using ImageMagick."""
    if os.path.isfile(image_with_path_type_png):
        try:
            if os.name == 'nt':
                identify = subprocess.check_output(['magick', 'identify', image_with_path_type_png], text=True)
            else:
                identify = subprocess.check_output(['identify', image_with_path_type_png], text=True)
            dimensions = identify.split(" ")[2].split("x")
            return True, int(dimensions[0]), int(dimensions[1])
        except Exception:
            return False, 0, 0
    return False, 0, 0

def display_cursor_type_a():
    """Cycle through Unicode arrow characters for display."""
    i = 0
    ascii_chars = ['←', '↖', '↑', '↗', '→', '↘', '↓', '↙']

    def get():
        nonlocal i
        i = (i + 1) % 8
        return ascii_chars[i]

    return get