# Photoscenary

Photoscenary.py is a Python program designed to generate and manipulate photoscenery tiles for the FlightGear Flight Simulator (FGFS). It downloads orthophotos from map servers (e.g., ArcGIS), processes them into tiles, and converts them to DDS or PNG format for use in FlightGear.This project is a Python-based adaptation of the [Julia Photoscenary generator](https://github.com/abassign/Photoscenary?tab=GPL-2.0-1-ov-file) by Adriano Bassignana (abassign). It retains the core functionality of the original while introducing enhancements such as parallel tile processing, maximum resolution for the origin tile, and support for both NVIDIA Texture Tools (NVTT) and ImageMagick for DDS conversion.

![Foto Grid Preview.](https://github.com/jeanmcal/Photoscenary_FGPhotopy/blob/main/photo-grid.png?raw=true)

**Note**: This is not a final product. It is a work-in-progress with ongoing development and testing. The debug mode (`-v 2`) provides detailed information about the processes being executed, which is useful for troubleshooting and monitoring.A list of changes and version history can be found in Versions.md.

# New Visual Interface and Code Improvements
![Interface Preview.](https://github.com/jeanmcal/Photoscenary_FGPhotopy/blob/main/Preview-img/Preview_Map06.PNG?raw=true)

## Description
- In the top right window we have the download settings.
  - **Search Airport:** Airport search bar.
  - **Show Airport Pins:** Enable and disable airport pins.
  - **Terrain Quality:** Changes the quality at which terrain images will be downloaded.
  - **Output Path:** Add the path to your Photoscenery folder.
  - **Conversion Method:** Choose the method that will convert the images to .dds.
    
    ### Buttons
  - **Reload Tiles:** Reload the 1x1 tiles to track the download progress. *(If the progress markers disappear, press to reload.)*
  - **Select Subtiles:** Select a 1x1 tile and press this button to **enable the subtile grid**. You can select which subtiles you want to download and their quality. **Customize it your way.**
  - **Download 1x1 Tiles:** Select as many 1x1 tiles as you want and press to download, they will all be downloaded in the quality defined in **Terrain Quality**
  - **Remove Selected Tiles:** Select the 1x1 tiles you want to delete and press to remove them. Also works in subtile mode.
 
    ### Subtiles Mode
  - Click on the desired 1x1 tile. The **Select Subtiles** button will appear. Pressing it will activate the **8x8** or **8x4** grid, depending on the region.
  - Clicking on a subtile will display a new window in the top left corner to select the quality each subtile will appear in.
  - Select as many as you want and the quality of each. To download, scroll to the bottom of the list and press **download**.
  - A loadspin will run on the currently loaded subtile, and when finished, it will be checked.     

## Quick Guide
 
1. Download the latest version of [FGPhotopy](https://github.com/jeanmcal/Photoscenary_FGPhotopy/releases/tag/V0.4.2).
2. Extract the files from the folder.
3. Install the external tools **[ImageMagick](https://imagemagick.org/script/download.php)** or **[NVIDIA Texture Tools Exporter](https://developer.nvidia.com/nvidia-texture-tools-exporter)**.
4. Open the **FGPhotopy.exe** and configure it your way.
5. In the FlightGear launcher, go to **Add-ons** > **Scenery**, And add the same path that is in **FGPhotopy**

# Use without interface

1. Install the required toolchain (Python, dependencies *If using the command-line terminal*, and external tools **ImageMagick** or **NVIDIA Texture Tools Exporter**).
2. Use the script to download and process photoscenery tiles in the correct format.
3. Configure FlightGear to load the generated tiles.

## Installation
### Prerequisites
To run Photoscenary.py, you need the following:
1. **Python 3.8+:**
    - Download and install from [python.org](https://www.python.org/downloads/).
    - Ensure Python is added to your system PATH.
      
2. **ImageMagick**
    - Required for creating mosaics and optional DDS conversion.
    - Download from [magemagick.org](https://imagemagick.org/script/download.php).
    - On Windows, select "Add application directory to your system path" during installation.
    - Restart your computer after installation.
      
3. **NVIDIA Texture Tools (Optional):**
    - Required for DDS conversion with NVTT (default converter, faster than ImageMagick).
    - Download from [NVIDIA Developer](https://developer.nvidia.com/nvidia-texture-tools-exporter).
    - Ensure `nvtt_export.exe` is located at `C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvtt_export.exe` (Windows) or adjust the path in the script.
    - **Note**: For high-resolution tiles (`-s 5`, 16384x16384), NVTT may fail due to high memory usage. Use `--converter imagemagick` or reduce the resolution to `-s 4` (8192x8192) or lower to avoid this issue.
      
4. **Python Dependencies:**
    - Install the required Python packages using the provided `requirements.txt`.
  
## Main Commands
  1. **Generate Photoscenery Along a Route:**
     
     To generate photoscenery along a route defined in a GPX or FGFS XML file (e.g., LIME to LIMJ), use:
     
     ```
     python photoscenary.py -r 20.0 -s 5 -f 1 -m 1 -o "C:\Users\Pc\Documents\Photoscenery" -t "LIME-LIMJ.gpx" -v 2 --converter imagemagick
     ```
  - Adjust `-r` (radius in nautical miles) and `-s` (tile size: 2=2048, 3=4096, 4=8192, 5=16384) based on your preference.
  - Use `--converter nvtt` for faster DDS conversion, but switch to `--converter imagemagick` if NVTT fails due to memory issues at `-s 5`.
    
  3. **Generate Photoscenery via FlightGear Telnet**
     
     ```
     python photoscenary.py -r 20.0 -s 5 -f 1 -m 1 -o "C:\Users\Pc\Documents\Photoscenery" -i "127.0.0.1:5000" -v 2 --converter imagemagick
     ```
  - Ensure FlightGear is running with Telnet enabled (e.g., `--telnet=5000`).
  - Adjust `-r` and `-s` as needed.

## **Command-Line Options**

- `-p, --proxy <url>:` Proxy server (e.g., `http://proxy:port`).
- `-r, --radius <nm>`: Radius in nautical miles (default: 10.0).
- `--center= <lat,lon|ICAO>`: Center point as coordinates (e.g., `45.66,9.7`) or ICAO code (e.g., `LIMJ`).
- `--bbox= <latLL,lonLL,latUR,lonUR>`: Bounding box coordinates (e.g., `45.5,9.5,45.7,9.9`).
- `-s, --size <0-5>`: Maximum tile size (0=512, 1=1024, 2=2048, 3=4096, 4=8192, 5=16384; default: 2).
- `-d, --size_dwn <0-5>`: Minimum tile size for distant tiles (default: 0).
- `-f, --format <0|1>`: Output format (0=PNG, 1=DDS; default: 1).
- `-m, --map_server <id>`: Map server ID (default: 1, ArcGIS).
- `-o, --output <path>`: Output directory (default: `C:\Users\Pc\Documents\Photoscenery` on Windows).
- `-i, --ip_port <ip:port>`: FlightGear Telnet IP and port (default: 127.0.0.1:5000).
- `-t, --route <file.gpx|file.xml>`: Route file in GPX or FGFS XML format.
- `-v, --debug <0-2>`: Debug level (0=minimal, 1=moderate, 2=verbose; default: 0).
- `--converter <nvtt|imagemagick>`: DDS converter (default: `nvtt`).

## Examples

  1. **Using Coordinates:**
     
     Download photoscenery around a specific coordinate (e.g., Bergamo, Italy) with a 15 nm radius and maximum resolution of 4096x4096:
     
     ```
     python photoscenary.py -o /home/user/photoscenery --center=45.66,9.7 -r 15 -s 3 -f 1 --converter imagemagick -v 2
     ```
    
  3. **Using Airport ICAO:**

     Generate photoscenery around Genova Airport (LIMJ):

     ```
     python photoscenary.py -o /home/user/photoscenery -i LIMJ -r 15 -s 3 -f 1 --converter imagemagick -v 2
     ```

  3. **Using a Bounding Box:**

     Download photoscenery for a specific rectangular area:

     ```
     python photoscenary.py -o /home/user/photoscenery --bbox=45.5,9.5,45.7,9.9 -s 4 -f 1 --converter imagemagick -v 2
     ```
## Using the Tiles in FlightGear
  
  To load the generated photoscenery in FlightGear:

  1. **Add the Photoscenery Folder:**

  - In the FlightGear launcher, go to **Add-ons** > **Scenery**.
  - Add the folder specified with `-o` (e.g., `/home/user/photoscenery`). This folder contains an `Orthophotos` subfolder with the tiles.

  2. **Enable Photoscenery:**

     - Start FlightGear with Telnet enabled if using real-time generation:
      ```       
      --telnet=5000
     ```
      - Go to `Menu` > `View` > `Rendering Options`.
      - Check the `Satellite Photoscenery` option to enable the photoscenery.

## Known Issues

  - **Runway Alignment:**
    - Some runways may appear slightly misaligned with their 3D models in FlightGear. This issue is also present in the original Julia Photoscenary generator. Attempts to correct alignment for one runway often cause larger misalignments in others. The current alignment is satisfactory for most use cases. A potential solution is to adjust runway positions in the FlightGear scenery database, but this is outside the scope of this project.
      
  - **Memory Issues with NVTT:**
    - When using `-s 5` (16384x16384 tiles), NVIDIA Texture Tools (`--converter nvtt`) may fail due to high memory usage. To mitigate this:
      - Switch to `--converter imagemagick` for DDS conversion.
      - Reduce the resolution to `-s 4` (8192x8192) or lower.

## Advanced Features

  - **Parallel Tile Processing:**
    - Tiles are processed in parallel using `ProcessPoolExecutor`, leveraging multiple CPU cores for faster execution. The number of workers is limited to `min(cpu_count(), 8)` to balance performance and memory usage.
    - Example log: `Using 8 workers for parallel tile processing`.

  - **Maximum Resolution for Origin Tile:**
    - The tile closest to the center point or first waypoint is always generated at the maximum resolution specified by `-s` (e.g., 16384x16384 for `-s 5` at low latitudes).

  - **Flexible DDS Conversion:**
    - Choose between NVIDIA Texture Tools (`--converter nvtt`, faster) or ImageMagick (`--converter imagemagick`, fallback) for DDS conversion.

  - **Dynamic Resolution:**
    - Tiles farther from the center use lower resolutions (controlled by `-d`) to optimize performance, except for the origin tile, which uses the maximum size.

  - **Debug Mode:**
    - Use `-v 2` to enable verbose logging, which provides detailed information about tile processing, download progress, and conversion steps. This is useful for debugging and understanding the script’s behavior.

 ## Troubleshooting 

   - **ImageMagick Errors:**
     - Ensure ImageMagick is installed and in your PATH. Run `magick -version` to verify.

   - **NVTT Errors:**
     - Verify that `nvtt_export.exe` is in the correct path. Update the path in `convert_png_to_dds` if needed.
     - Use `--converter imagemagick` if memory issues occur with `-s 5`.

   - **Missing Tiles:**
     - Check the debug output (`-v 2`) for errors (e.g., network issues, server rate limits).
     - Ensure `params.xml` is correctly configured with the map server details.

   - **Performance Issues:**
   - For large tiles (`-s 5`), ensure sufficient RAM (16GB+ recommended).
   - Reduce `max_workers` in `process_tiles` if memory usage is too high.
   - in the code you will find in the following line, if you want to change the value: `with ThreadPoolExecutor(max_workers=4) as executor:`
   - I recommend using 4, you can test 8 or more, but it can generate a timeout when requesting the map server, making the process take longer.

## Credits

Photoscenary.py is a clone of the Julia Photoscenary generator by Adriano Bassignana. Full credit goes to abassign for the original concept, design, and implementation. This Python version builds upon their work, adapting it to Python with additional optimizations while maintaining compatibility with FlightGear.

## Contributing

  Please include tests and update Versions.md with your changes.

## License

Photoscenary.py is licensed under the GNU General Public License v2 (GPL-2.0). See LICENSE for details.

     

    



