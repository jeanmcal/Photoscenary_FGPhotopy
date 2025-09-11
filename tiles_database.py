# License: GPL 2
# TilesDatabase module for managing tile data

from dataclasses import dataclass
import pandas as pd
import os
from pathlib import Path
import shutil
from commons import coord_from_index, get_file_extension, get_file_name, get_dds_size, get_png_size
from scandir import walkdir

@dataclass
class TailCoordinates:
    lon_deg: float
    lat_deg: float
    lon: int
    lat: int
    x: int
    y: int

    def __init__(self, index: int):
        self.lon_deg, self.lat_deg, self.lon, self.lat, self.x, self.y, _, _ = coord_from_index(index)

@dataclass
class TailData:
    path: str | None
    name: str
    mod_date: float
    size: int
    pixel_size_w: int
    pixel_size_h: int
    format: int

@dataclass
class TailGroupByIndex:
    index: int = 0
    files_found: list = None
    coordinates: TailCoordinates | None = None
    time_last_scan: float = 0.0

    def __init__(self):
        self.files_found = []

def tail_group_by_index_insert(tgi: TailGroupByIndex, index: int, tail_data: TailData):
    """Insert tail data into TailGroupByIndex."""
    tgi.index = index
    tgi.files_found.append(tail_data)
    tgi.coordinates = TailCoordinates(index)
    tgi.time_last_scan = time.time()

def get_tail_group_by_index(db: pd.DataFrame, index: int, path: str = None):
    """Retrieve tail group by index."""
    records = db[db["key"] == index]
    if len(records) > 0:
        tail_group = records.iloc[0]["Value"]
        if path is not None:
            for record in tail_group.files_found:
                if path in record.path and record.path.startswith(path):
                    return record, tail_group.coordinates
            return None
        return tail_group
    return None

def copy_tiles_by_index(db: pd.DataFrame, index: int, pixel_size_w: int, a_base_path: str, a_format: int):
    """Copy tiles by index to destination path."""
    records = get_tail_group_by_index(db, index)
    file_ext = ".png" if a_format == 0 else ".dds"
    data_found = None
    if records:
        is_skip = False
        for record in records.files_found:
            if record.pixel_size_w == pixel_size_w and record.format == a_format and not is_skip:
                cfi = coord_from_index(index)
                base_path = os.path.normpath(os.path.join(a_base_path, cfi[6], cfi[7]))
                dest_path = os.path.join(base_path, f"{index}{file_ext}")
                if record.path != dest_path:
                    os.makedirs(base_path, exist_ok=True)
                    shutil.copy2(record.path, dest_path)
                    is_skip = False
                else:
                    is_skip = True
                data_found = (index, record.path, base_path, is_skip)
        return data_found
    print(f"copyTilesByIndex {index} {a_base_path} {a_format} - record not found")
    return None

def move_or_delete_tiles(index: int, path_from_base: str, format: int, path_to_base: str | None = None):
    """Move or delete tiles based on validity."""
    cfi = coord_from_index(index)
    file_ext = ".png" if format == 0 else ".dds"
    file_from_with_path = os.path.normpath(os.path.join(path_from_base, cfi[6], cfi[7], f"{index}{file_ext}"))
    is_correct, pixel_size_w, pixel_size_h = get_dds_size(file_from_with_path) if format == 1 else get_png_size(file_from_with_path)
    try:
        if is_correct and path_to_base:
            base_to_with_path = os.path.normpath(os.path.join(path_to_base, str(pixel_size_w), cfi[6], cfi[7]))
            os.makedirs(base_to_with_path, exist_ok=True)
            shutil.move(file_from_with_path, os.path.join(base_to_with_path, f"{index}{file_ext}"))
        else:
            if os.path.exists(file_from_with_path):
                os.remove(file_from_with_path)
    except Exception as err:
        print(f"moveOrDeleteTiles - Error: {err}")

def create_files_list_type_dds_and_png(path_search: str | None = None, root_path: str | None = None, path_save: str | None = None):
    """Create a list of DDS and PNG files."""
    if path_search is None:
        path_search = os.path.expanduser("~")
    if root_path and path_search in root_path:
        root_path = None
    if path_save and path_search in path_save:
        path_save = None
    rows_number = 0
    dds_file_number = 0
    png_file_number = 0
    files_size = 0
    time_start = time.time()
    tiles_files = {}

    for path in (path_search, root_path, path_save):
        if path:
            print(f"\nSearch and test the DDS/PNG files in path: {path}")
            if os.path.exists(path):
                for root, dirs, files in walkdir(path):
                    if root != os.path.expanduser("~"):
                        for file in files:
                            fe = get_file_extension(file)
                            if fe and fe.upper() in (".DDS", ".PNG"):
                                index = int(get_file_name(file)) if get_file_name(file).isdigit() else None
                                if index:
                                    cfi = coord_from_index(index)
                                    slash = "\\" if os.name == "nt" else "/"
                                    file_with_path = os.path.join(cfi[6], cfi[7], f"{index}{fe.lower()}")
                                    jp = os.path.join(root, file)
                                    if file_with_path in jp:
                                        is_correct, pixel_size_w, pixel_size_h = get_dds_size(jp) if fe.upper() == ".DDS" else get_png_size(jp)
                                        if is_correct:
                                            format = 1 if fe.upper() == ".DDS" else 0
                                            td = TailData(jp, file, os.path.getmtime(jp), os.path.getsize(jp), pixel_size_w, pixel_size_h, format)
                                            if index not in tiles_files:
                                                tiles_files[index] = TailGroupByIndex()
                                            tail_group_by_index_insert(tiles_files[index], index, td)
                                            rows_number += 1
                                            if format == 1:
                                                dds_file_number += 1
                                            else:
                                                png_file_number += 1
                                            files_size += os.path.getsize(jp)
                                        else:
                                            if os.path.isfile(jp):
                                                os.remove(jp)
                        print(f"\rExecute update images files, find n. {rows_number} DDS files: {dds_file_number} PNG files: {png_file_number} with size: {int(files_size/1000000.0)} Mb Time: {time.time() - time_start:.1f}")
            else:
                print(f"\nError: not found the root path: {path}")
    print(f"\nTerm update DDS/PNG list files")
    df = pd.DataFrame([(k, v) for k, v in tiles_files.items()], columns=["key", "Value"])
    return df