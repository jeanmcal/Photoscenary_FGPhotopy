Photoscenary.pyPhotoscenary.py is a Python program designed to generate and manipulate photoscenery tiles for the FlightGear Flight Simulator (FGFS). It downloads orthophotos from map servers (e.g., ArcGIS), processes them into tiles, and converts them to DDS or PNG format for use in FlightGear.This project is a Python-based adaptation of the Julia Photoscenary generator by Adriano Bassignana (abassign). It retains the core functionality of the original while introducing enhancements such as parallel tile processing, maximum resolution for the origin tile, and support for both NVIDIA Texture Tools (NVTT) and ImageMagick for DDS conversion.Note: This is not a final product. It is a work-in-progress with ongoing development and testing. The debug mode (-v 2) provides detailed information about the processes being executed, which is useful for troubleshooting and monitoring.A list of changes and version history can be found in Versions.md.CreditsPhotoscenary.py is a clone of the Julia Photoscenary generator by Adriano Bassignana. Full credit goes to abassign for the original concept, design, and implementation. This Python version builds upon their work, adapting it to Python with additional optimizations while maintaining compatibility with FlightGear.Quick GuideDetailed instructions are available in the FlightGear Wiki (to be created or linked if applicable). The process to generate photoscenery is straightforward:Install the required toolchain (Python, dependencies, and external tools).
Use the script to download and process photoscenery tiles in the correct format.
Configure FlightGear to load the generated tiles.

InstallationPrerequisitesTo run Photoscenary.py, you need the following:Python 3.8+:Download and install from python.org.
Ensure Python is added to your system PATH.

ImageMagick:Required for creating mosaics and optional DDS conversion.
Download from imagemagick.org.
On Windows, select "Add application directory to your system path" and "Install legacy utilities (e.g., convert)" during installation.
Restart your computer after installation.

NVIDIA Texture Tools (Optional):Required for DDS conversion with NVTT (default converter, faster than ImageMagick).
Download from NVIDIA Developer.
Ensure nvtt_export.exe is located at C:\Program Files\NVIDIA Corporation\NVIDIA Texture Tools\nvtt_export.exe (Windows) or adjust the path in the script.
Note: For high-resolution tiles (-s 5, 16384x16384), NVTT may fail due to high memory usage. Use --converter imagemagick or reduce the resolution to -s 4 (8192x8192) or lower to avoid this issue.

Python Dependencies:Install the required Python packages using the provided requirements.txt.

Installation StepsClone the Repository:bash

git clone https://github.com/yourusername/photoscenary-py.git
cd photoscenary-py

Alternatively, download the ZIP file from the repository and extract it.
Set Up a Virtual Environment (Recommended):bash

python -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

Install Dependencies:
Create a requirements.txt file with the following content:plaintext

requests==2.32.5
Pillow==11.3.0
Wand==0.6.13
numpy==2.3.2
pandas==2.3.2
geopy==2.4.1
gpxpy==1.6.2
tqdm==4.67.1

Then install:bash

pip install -r requirements.txt

Verify External Tools:Run the script with the --version flag to check if ImageMagick and NVTT are correctly installed:bash

python photoscenary.py --version

UsagePhotoscenary.py is a command-line tool. Use the following commands to run it:Help:bash

python photoscenary.py -h

Displays version information and command-line options.
Version Check:bash

python photoscenary.py --version

Prints the version and checks for required external programs (ImageMagick, NVTT).

Main CommandsGenerate Photoscenery Along a Route:
To generate photoscenery along a route defined in a GPX or FGFS XML file (e.g., LIME to LIMJ), use:bash

python photoscenary.py -r 20.0 -s 5 -f 1 -m 1 -o "C:\Users\Pc\Documents\Photoscenery" -t "LIME-LIMJ.gpx" -v 2 --converter imagemagick

Adjust -r (radius in nautical miles) and -s (tile size: 0=512, 1=1024, 2=2048, 3=4096, 4=8192, 5=16384) based on your preference.
Use --converter nvtt for faster DDS conversion, but switch to --converter imagemagick if NVTT fails due to memory issues at -s 5.

Generate Photoscenery via FlightGear Telnet:
To generate photoscenery in real-time based on the aircraft’s position in FlightGear, use:bash

python photoscenary.py -r 20.0 -s 5 -f 1 -m 1 -o "C:\Users\Pc\Documents\Photoscenery" -i "127.0.0.1:5000" -v 2 --converter imagemagick

Ensure FlightGear is running with Telnet enabled (e.g., --telnet=5000).
Adjust -r and -s as needed.

Command-Line Options-p, --proxy <url>: Proxy server (e.g., http://proxy:port).
-r, --radius <nm>: Radius in nautical miles (default: 10.0).
-c, --center <lat,lon|ICAO>: Center point as coordinates (e.g., 45.66,9.7) or ICAO code (e.g., LIMJ).
-b, --bbox <latLL,lonLL,latUR,lonUR>: Bounding box coordinates (e.g., 45.5,9.5,45.7,9.9).
-s, --size <0-5>: Maximum tile size (0=512, 1=1024, 2=2048, 3=4096, 4=8192, 5=16384; default: 2).
-d, --size_dwn <0-5>: Minimum tile size for distant tiles (default: 0).
-f, --format <0|1>: Output format (0=PNG, 1=DDS; default: 1).
-m, --map_server <id>: Map server ID (default: 1, ArcGIS).
-o, --output <path>: Output directory (default: C:\Users\Pc\Documents\Photoscenery on Windows).
-i, --ip_port <ip:port>: FlightGear Telnet IP and port (default: 127.0.0.1:5000).
-t, --route <file.gpx|file.xml>: Route file in GPX or FGFS XML format.
-v, --debug <0-2>: Debug level (0=minimal, 1=moderate, 2=verbose; default: 0).
--converter <nvtt|imagemagick>: DDS converter (default: nvtt).

ExamplesUsing Coordinates:
Download photoscenery around a specific coordinate (e.g., Bergamo, Italy) with a 15 nm radius and maximum resolution of 4096x4096:bash

python photoscenary.py -o /home/user/photoscenery -c 45.66,9.7 -r 15 -s 3 -f 1 --converter imagemagick -v 2

Using Airport ICAO:
Generate photoscenery around Genova Airport (LIMJ):bash

python photoscenary.py -o /home/user/photoscenery -i LIMJ -r 15 -s 3 -f 1 --converter imagemagick -v 2

Using a Bounding Box:
Download photoscenery for a specific rectangular area:bash

python photoscenary.py -o /home/user/photoscenery -b 45.5,9.5,45.7,9.9 -s 4 -f 1 --converter imagemagick -v 2

Using the Tiles in FlightGearTo load the generated photoscenery in FlightGear:Add the Photoscenery Folder:In the FlightGear launcher, go to Add-ons > Scenery.
Add the folder specified with -o (e.g., /home/user/photoscenery). This folder contains an Orthophotos subfolder with the tiles.

Enable Photoscenery:Start FlightGear with Telnet enabled if using real-time generation:bash

fgfs --aircraft=c172p --telnet=5000 --flight-plan=/path/to/LIME-LIMJ.gpx

Go to Menu > View > Rendering Options.
Check the Satellite Photoscenery option to enable the photoscenery.

Known IssuesRunway Alignment:Some runways may appear slightly misaligned with their 3D models in FlightGear. This issue is also present in the original Julia Photoscenary generator. Attempts to correct alignment for one runway often cause larger misalignments in others. The current alignment is satisfactory for most use cases. A potential solution is to adjust runway positions in the FlightGear scenery database, but this is outside the scope of this project.

Memory Issues with NVTT:When using -s 5 (16384x16384 tiles), NVIDIA Texture Tools (--converter nvtt) may fail due to high memory usage. To mitigate this:Switch to --converter imagemagick for DDS conversion.
Reduce the resolution to -s 4 (8192x8192) or lower.

Advanced FeaturesParallel Tile Processing:Tiles are processed in parallel using ProcessPoolExecutor, leveraging multiple CPU cores for faster execution. The number of workers is limited to min(cpu_count(), 8) to balance performance and memory usage.
Example log: Using 8 workers for parallel tile processing.

Maximum Resolution for Origin Tile:The tile closest to the center point or first waypoint is always generated at the maximum resolution specified by -s (e.g., 16384x16384 for -s 5 at low latitudes).

Flexible DDS Conversion:Choose between NVIDIA Texture Tools (--converter nvtt, faster) or ImageMagick (--converter imagemagick, fallback) for DDS conversion.

Dynamic Resolution:Tiles farther from the center use lower resolutions (controlled by -d) to optimize performance, except for the origin tile, which uses the maximum size.

Debug Mode:Use -v 2 to enable verbose logging, which provides detailed information about tile processing, download progress, and conversion steps. This is useful for debugging and understanding the script’s behavior.

TroubleshootingImageMagick Errors:Ensure ImageMagick is installed and in your PATH. Run magick -version to verify.
If using Windows, install legacy utilities (convert).

NVTT Errors:Verify that nvtt_export.exe is in the correct path. Update the path in convert_png_to_dds if needed.
Use --converter imagemagick if memory issues occur with -s 5.

Missing Tiles:Check the debug output (-v 2) for errors (e.g., network issues, server rate limits).
Ensure params.xml is correctly configured with the map server details.

Performance Issues:For large tiles (-s 5), ensure sufficient RAM (16GB+ recommended).
Reduce max_workers in process_tiles if memory usage is too high.

ContributingContributions are welcome! To contribute:Fork the repository.
Create a branch (git checkout -b feature/your-feature).
Commit your changes (git commit -m "Add your feature").
Push to the branch (git push origin feature/your-feature).
Open a Pull Request.

Please include tests and update Versions.md with your changes.LicensePhotoscenary.py is licensed under the GNU General Public License v2 (GPL-3.0). See LICENSE for details.

