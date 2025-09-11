// Initialize map layers for 1x1 tiles, .dds subtiles, and airport markers
const tileLayer = L.layerGroup();
const ddsLayer = L.layerGroup();
const subtileLayer = L.layerGroup();
const airportLayer = L.markerClusterGroup({
    maxClusterRadius: 50,
    disableClusteringAtZoom: 10,
    spiderfyOnMaxZoom: false
});
window.tileLayers = []; // Prevent TypeError
const tilesLayers = {};
let tileStatusCache = {};
let lastZoomLevel = null;
const map = L.map('map', {
    layers: [tileLayer, ddsLayer, subtileLayer, airportLayer],
    zoomControl: true,
    minZoom: 5,
    maxZoom: 15
}).setView([-19, -45], 10);

// User settings
let outputPath = 'C:\\Users\\Pc\\Documents\\Photoscenery'; // Default path, overridden by config

// Quality color mapping
const QUALITY_COLORS = {
    '2': '#ff0000', // Medium-Low (red)
    '3': '#ffff00', // Medium (yellow)
    '4': '#00ff00', // High (green)
    '5': '#00e1ffff' // Maximum (purple)
};

// Application state
let drawnTiles = {};
let selectedTiles = [];
let selectedSubtiles = [];
let isDownloading = false;
let isSubtileMode = false;
let allAirports = [];
let visibleAirports = [];

async function saveConfig() {
    /** Save user configuration to the server. */
    const config = {
        output_path: outputPath,
        quality_terrain: document.getElementById('quality-terrain').value,
        map_center: map.getCenter(),
        map_zoom: map.getZoom(),
        converter: document.getElementById('converter').value,
        show_airports: document.getElementById('toggle-airports').checked // Save checkbox state
    };
    console.log('Saving configuration:', config);
    try {
        const response = await fetch('/api/save_config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        const data = await response.json();
        if (data.status === 'success') {
            console.log('Configuration saved successfully');
        } else {
            console.error('Error saving configuration:', data.message);
            logMessage(`Error saving configuration: ${data.message}`);
        }
    } catch (error) {
        console.error('Error saving configuration:', error);
        logMessage(`Error saving configuration: ${error}`);
    }
}

// Satellite imagery layer (Esri World Imagery)
const esriWorldImagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 15
}).addTo(map);

// Label layer for hybrid style (Esri World Transportation)
const esriWorldTransportation = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri',
    maxZoom: 15
}).addTo(map);

function parseTileName(tile) {
    /** Parse tile name to extract latitude and longitude. */
    console.log('parseTileName input:', tile);
    const parts = tile.split('-');
    let latitude, longitude;
    if (parts[0] === '') {
        latitude = parseFloat(`-${parts[1]}`);
        longitude = parseFloat(`-${parts[3] || parts[2]}`);
    } else {
        latitude = parseFloat(parts[0]);
        longitude = parseFloat(parts[1]);
        if (parts[2]) longitude = parseFloat(`-${parts[2]}`);
    }
    console.log('parseTileName output:', [latitude, longitude]);
    return [latitude, longitude];
}

function generateFolderName(latitude, longitude) {
    /** Generate folder name based on latitude and longitude. */
    const lonPrefix = longitude >= 0 ? 'e' : 'w';
    const latPrefix = latitude >= 0 ? 'n' : 's';
    return `${lonPrefix}${Math.abs(longitude).toString().padStart(3, '0')}${latPrefix}${Math.abs(latitude).toString().padStart(2, '0')}`;
}

function getTileWidth(latitude) {
    /** Return tile width in degrees based on latitude. */
    const absLat = Math.abs(parseFloat(latitude));
    if (absLat >= 89.0) return 12.0;
    if (absLat >= 86.0) return 4.0;
    if (absLat >= 83.0) return 2.0;
    if (absLat >= 76.0) return 1.0;
    if (absLat >= 62.0) return 0.5;
    if (absLat > 22.0) return 0.25;
    return 0.125;
}

function calculateTileId(latitude, longitude, row, col) {
    /** Calculate FlightGear tile index for a subtile. */
    const lonIndex = Math.floor(longitude) + 180;
    const latIndex = Math.floor(latitude) + 90;
    return (lonIndex << 14) + (latIndex << 6) + (row << 3) + col;
}

async function loadAirports() {
    /** Load global and visible airports based on map bounds. */
    const bounds = map.getBounds();
    const bbox = `${bounds.getSouth()},${bounds.getWest()},${bounds.getNorth()},${bounds.getEast()}`;
    console.log(`Loading visible airports for bbox: ${bbox}`);

    if (!allAirports.length) {
        try {
            const response = await fetch('/api/airports');
            allAirports = await response.json();
            console.log(`Loaded ${allAirports.length} global airports`);
            updateSearchResults('');
            await loadVisibleAirports(bbox);
        } catch (error) {
            console.error('Error loading global airports:', error);
            logMessage(`Error loading global airports: ${error}`);
        }
    } else {
        await loadVisibleAirports(bbox);
    }
}

async function loadVisibleAirports(bbox) {
    /** Load and display airports within the specified bounding box. */
    try {
        const response = await fetch(`/api/airports?bbox=${bbox}`);
        const airports = await response.json();
        console.log(`Received ${airports.length} visible airports`);
        airportLayer.clearLayers();
        visibleAirports = airports;
        airports.forEach(airport => {
            const marker = L.marker([airport.lat, airport.lon])
                .bindPopup(`Airport: ${airport.icao} (${airport.name})`);
            airportLayer.addLayer(marker);
        });
        console.log('Visible airport markers added to map');
    } catch (error) {
        console.error('Error loading visible airports:', error);
        logMessage(`Error loading visible airports: ${error}`);
    }
}

function updateSearchResults(query) {
    /** Update the airport search results based on the query. */
    const searchResults = document.getElementById('search-results');
    searchResults.innerHTML = '';
    if (!query) {
        searchResults.style.display = 'none';
        return;
    }
    const filtered = allAirports
        .filter(airport =>
            airport.icao.toLowerCase().includes(query.toLowerCase()) ||
            airport.name.toLowerCase().includes(query.toLowerCase())
        )
        .slice(0, 10);
    if (filtered.length > 0) {
        searchResults.style.display = 'block';
        filtered.forEach(airport => {
            const div = document.createElement('div');
            div.textContent = `${airport.icao} - ${airport.name}`;
            div.onclick = () => {
                map.setView([airport.lat, airport.lon], 12);
                searchResults.innerHTML = '';
                searchResults.style.display = 'none';
                document.getElementById('search-bar').value = '';
            };
            searchResults.appendChild(div);
        });
    } else {
        searchResults.style.display = 'none';
    }
}

async function checkTileFolders(tiles, callback, silent = false) {
    /** Check if tiles exist in the output directory and update their status. */
    console.log('Checking tiles:', tiles);
    const zoomLevel = map.getZoom();
    const checkLevel = zoomLevel < 7 ? 'folder' : 'file';
    const tilesToCheck = tiles.filter(tile => {
        if (!(tile in tileStatusCache)) return true;
        return tileStatusCache[tile].check_level !== checkLevel;
    });

    if (!tilesToCheck.length) {
        console.log('All tiles are cached with the correct mode');
        callback(tiles.reduce((acc, tile) => ({ ...acc, [tile]: tileStatusCache[tile] }), {}));
        return;
    }

    if (!outputPath || outputPath.trim() === '') {
        logMessage('Error: Output path cannot be empty.');
        callback({});
        return;
    }

    try {
        const response = await fetch('/api/check_tiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tiles: tilesToCheck,
                silent,
                check_level: checkLevel,
                output_path: outputPath
            })
        });
        const data = await response.json();
        console.log('Folder status:', data);

        if (data.status === 'error') {
            logMessage(`Error checking tiles: ${data.message}`);
            callback({});
            return;
        }

        Object.keys(data).forEach(tile => {
            data[tile].check_level = checkLevel;
        });
        Object.assign(tileStatusCache, data);
        window.tileLayers.forEach(layer => map.removeLayer(layer));
        window.tileLayers = [];
        ddsLayer.clearLayers();

        tiles.forEach(tile => {
            const [latitude, longitude] = parseTileName(tile);
            const status = data[tile] || tileStatusCache[tile];
            const folderName = generateFolderName(latitude, longitude);

            if (status && status.found) {
                if (checkLevel === 'folder') {
                    const bounds = [[latitude, longitude], [latitude + 1, longitude + 1]];
                    const rectangle = L.rectangle(bounds, {
                        color: '#00ff00',
                        fillColor: '#00ff00',
                        fillOpacity: 0.3,
                        weight: 1
                    }).addTo(tileLayer);
                    window.tileLayers.push(rectangle);
                    console.log(`Drawn green 1x1 tile for ${tile} (${folderName})`);
                } else {
                    status.dds_files.forEach(dds => {
                        const bounds = [[dds.min_lat, dds.min_lon], [dds.max_lat, dds.max_lon]];
                        const rectangle = L.rectangle(bounds, {
                            color: '#00ff00',
                            fillColor: '#00ff00',
                            fillOpacity: 0.3,
                            weight: 1
                        }).addTo(ddsLayer);
                        window.tileLayers.push(rectangle);
                        console.log(`Drawn rectangle for ${tile}, tile_id=${dds.tile_id}: ${JSON.stringify(bounds)}`);
                    });
                }
            } else {
                const bounds = [[latitude, longitude], [latitude + 1, longitude + 1]];
                const rectangle = L.rectangle(bounds, {
                    color: '#3388ff',
                    fill: false,
                    dashArray: '5, 10'
                }).addTo(tileLayer);
                window.tileLayers.push(rectangle);
                console.log(`Drawn dashed blue 1x1 tile for ${tile} (${folderName})`);
            }
        });
        callback(data);
    } catch (error) {
        logMessage(`Error checking tiles: ${error}`);
        console.error('Error checking tiles:', error);
        callback({});
    }
}

function selectTile(latitude, longitude, tileName) {
    /** Highlight a selected tile on the map by updating its style. */
    logMessage(`Tile selected: ${tileName} (lat: ${latitude}, lon: ${longitude})`);
    const bounds = [[latitude, longitude], [latitude + 1, longitude + 1]];
    const folderName = generateFolderName(latitude, longitude);
    const zoomLevel = map.getZoom();
    const weight = zoomLevel < 7 ? 2 : 1;

    if (drawnTiles[tileName]) {
        // Update existing tile's style
        drawnTiles[tileName].setStyle({
            color: '#ff0000',
            weight: 5,
            fillOpacity: 0.1,
            zIndex: 1005,
            dashArray: ''
        });
    } else {
        // Create new tile rectangle
        drawnTiles[tileName] = L.rectangle(bounds, {
            color: '#ff0000',
            weight: 5,
            fillOpacity: 0.1,
            zIndex: 1005,
            dashArray: ''
        }).addTo(tileLayer)
          .bindTooltip(folderName, {
              permanent: false,
              direction: 'center',
              className: 'leaflet-tooltip'
          })
          .on('click', () => {
              toggleTileSelection(tileName, latitude, longitude);
              document.getElementById('tile-code').textContent = folderName;
          });
    }
}

function addTileRectangle(latitude, longitude, tileName) {
    /** Add a clickable tile rectangle to the map. */
    const bounds = [[latitude, longitude], [latitude + 1, longitude + 1]];
    const folderName = generateFolderName(latitude, longitude);
    const layer = L.rectangle(bounds, {
        color: '#3388ff',
        weight: 1,
        fillOpacity: 0,
        dashArray: '5, 5'
    }).addTo(tileLayer);
    layer.bindTooltip(folderName, {
        permanent: false,
        direction: 'center',
        className: 'leaflet-tooltip'
    });
    layer.on('click', () => {
        toggleTileSelection(tileName, latitude, longitude);
        document.getElementById('tile-code').textContent = folderName;
    });
    return layer;
}

async function drawTiles(tiles, updateAll = true) {
    /** Draw tiles on the map based on their status. */
    const zoomLevel = map.getZoom();
    const checkLevel = zoomLevel < 7 ? 'folder' : 'file';
    const weight = zoomLevel < 7 ? 2 : 1;

    if (updateAll) {
        tileLayer.clearLayers();
        ddsLayer.clearLayers();
        drawnTiles = {};
    }

    await checkTileFolders(tiles, (folderStatus) => {
        tiles.forEach(tile => {
            const [latitude, longitude] = parseTileName(tile);
            if (latitude === null || longitude === null) {
                logMessage(`Error: Invalid coordinates for tile ${tile}`);
                return;
            }

            const folderName = generateFolderName(latitude, longitude);
            if (!drawnTiles[tile] || updateAll) {
                const bounds = [[latitude, longitude], [latitude + 1, longitude + 1]];
                const isSelected = selectedTiles.includes(tile);
                const status = folderStatus[tile] || tileStatusCache[tile];
                let tileStyle = {
                    color: isSelected ? '#ff0000' : '#a8a8a8b6',
                    weight: isSelected ? 5 : weight*2,
                    fillOpacity: isSelected ? 0.1 : 0.1,
                    zIndex: isSelected ? 1005 : 1000,
                    dashArray: isSelected ? '' : '5, 5'
                };
                if (status && status.found && status.check_level === checkLevel && !isSelected) {
                    if (checkLevel === 'folder') {
                        tileStyle = {
                            color: '#00ff00',
                            fillColor: '#00ff00',
                            fillOpacity: 0.3,
                            weight,
                            dashArray: ''
                        };
                    }
                }
                // Remove any existing layers for this tile to prevent duplicates
                tileLayer.eachLayer(layer => {
                    const layerBounds = layer.getBounds();
                    if (layer !== drawnTiles[tile] &&
                        layerBounds.getSouthWest().lat === latitude &&
                        layerBounds.getSouthWest().lng === longitude) {
                        tileLayer.removeLayer(layer);
                        console.log(`Removed duplicate layer for tile ${tile} during draw`);
                    }
                });
                const tileRect = L.rectangle(bounds, tileStyle)
                    .addTo(tileLayer)
                    .bindTooltip(folderName, {
                        permanent: false,
                        direction: 'center',
                        className: 'leaflet-tooltip'
                    });
                if (!isSubtileMode) {
                    tileRect.on('click', () => {
                        toggleTileSelection(tile, latitude, longitude);
                        document.getElementById('tile-code').textContent = folderName;
                    });
                }
                drawnTiles[tile] = tileRect;
            } else if (selectedTiles.includes(tile)) {
                drawnTiles[tile].setStyle({
                    color: '#ff0000',
                    weight: 5,
                    fillOpacity: 0.1,
                    zIndex: 1005,
                    dashArray: ''
                });
            }
        });

        if (isSubtileMode && selectedTiles.length === 1) {
            const tile = selectedTiles[0];
            const [latitude, longitude] = parseTileName(tile);
            drawSubtiles(tile, latitude, longitude);
        }
    }, !updateAll);
}

function toggleTileSelection(tile, latitude, longitude) {
    /** Toggle the selection state of a tile. */
    const folderName = generateFolderName(latitude, longitude);
    if (!selectedTiles.includes(tile)) {
        selectedTiles.push(tile);
        logMessage(`Tile selected: ${tile} (${folderName}, lat: ${latitude}, lon: ${longitude})`);
        selectTile(latitude, longitude, tile);
    } else {
        selectedTiles = selectedTiles.filter(t => t !== tile);
        logMessage(`Tile deselected: ${tile}`);
        if (drawnTiles[tile]) {
            const status = tileStatusCache[tile];
            const zoomLevel = map.getZoom();
            const weight = zoomLevel < 7 ? 2 : 1;
            const style = status && status.found && status.check_level === (zoomLevel < 7 ? 'folder' : 'file')
                ? {
                    color: '#00ff00',
                    fillColor: '#00ff00',
                    fillOpacity: 0.3,
                    weight,
                    dashArray: ''
                }
                : {
                    color: '#3388ff',
                    weight,
                    fillOpacity: 0,
                    dashArray: '5, 5'
                };
            drawnTiles[tile].setStyle(style);
            // Ensure no duplicate layers remain in tileLayer
            tileLayer.eachLayer(layer => {
                const layerBounds = layer.getBounds();
                if (layer !== drawnTiles[tile] &&
                    layerBounds.getSouthWest().lat === latitude &&
                    layerBounds.getSouthWest().lng === longitude) {
                    tileLayer.removeLayer(layer);
                    console.log(`Removed duplicate layer for tile ${tile}`);
                }
            });
        }
    }
    updateSelectedTilesDisplay();
}

function updateSelectedTilesDisplay() {
    /** Update the display of selected tiles. */
    const selectedTilesList = document.getElementById('selected-tiles');
    const downloadSubtilesButton = document.getElementById('download-subtiles');
    if (selectedTilesList) {
        selectedTilesList.innerHTML = selectedTiles.length > 0
            ? `Selected tiles: ${selectedTiles.join(', ')}`
            : 'No tiles selected';
    }
    if (downloadSubtilesButton) {
        downloadSubtilesButton.style.display = selectedTiles.length === 1 ? 'block' : 'none';
    }
}

async function removeSelectedTiles() {
    /** Remove selected tiles or subtiles from the output directory. */
    if (!selectedTiles.length && !selectedSubtiles.length) {
        logMessage('No tiles or subtiles selected for removal.');
        return;
    }

    if (!outputPath || outputPath.trim() === '') {
        logMessage('Error: Output path cannot be empty.');
        return;
    }

    const tilesToRemove = isSubtileMode ? [] : selectedTiles;
    const subtilesToRemove = isSubtileMode ? selectedSubtiles.map(subtile => {
        const parts = subtile.subtileId.split('_');
        const row = parseInt(parts[1]);
        const col = parseInt(parts[2]);
        const [latitude, longitude] = parseTileName(subtile.tile);
        return {
            parent_tile: subtile.tile,
            tile_id: calculateTileId(latitude, longitude, row, col)
        };
    }) : [];

    try {
        const response = await fetch('/api/remove_tiles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                tiles: tilesToRemove,
                subtiles: subtilesToRemove,
                output_path: outputPath
            })
        });
        const data = await response.json();
        if (data.status === 'success' || data.status === 'partial') {
            data.deleted.forEach(msg => logMessage(msg));
            if (data.errors.length > 0) {
                data.errors.forEach(err => logMessage(`Error: ${err}`));
            }
            if (isSubtileMode) {
                selectedSubtiles = [];
                updateSubtilesList();
                const parentTile = selectedTiles[0];
                if (tilesToRemove.includes(parentTile)) {
                    delete tileStatusCache[parentTile];
                }
            } else {
                selectedTiles.forEach(tile => delete tileStatusCache[tile]);
                selectedTiles = [];
                selectedSubtiles = [];
                updateSubtilesList();
            }
            updateSelectedTilesDisplay();
            await reloadTiles();
        } else {
            logMessage(`Error removing tiles/subtiles: ${data.message}`);
        }
    } catch (error) {
        logMessage(`Error removing tiles/subtiles: ${error}`);
    }
}

function drawSubtiles(tile, latitude, longitude) {
    /** Draw subtiles for a selected tile. */
    subtileLayer.clearLayers();
    const stepLat = 0.125; // Fixed subtile height: 1° / 8
    const cols = Math.abs(latitude) > 22.5 ? 4 : 8; // 4 columns for |lat| > 22.5°, 8 otherwise
    const stepLon = 1.0 / cols; // Subtile width: 1° / cols
    const subtileBounds = [];

    console.log(`Generating ${8 * cols} subtiles (8x${cols}) for tile ${tile} at latitude ${latitude}`);

    for (let row = 0; row < 8; row++) {
        for (let col = 0; col < cols; col++) {
            const subtileLat = latitude + row * stepLat;
            const subtileLon = longitude + col * stepLon;
            const bounds = [[subtileLat, subtileLon], [subtileLat + stepLat, subtileLon + stepLon]];
            const subtileId = `${tile}_${row}_${col}`;
            const tileId = calculateTileId(latitude, longitude, row, col);

            const selectedSubtile = selectedSubtiles.find(s => s.subtileId === subtileId);
            const isSelected = !!selectedSubtile;
            const quality = isSelected ? selectedSubtile.quality : '2';

            const rectangle = L.rectangle(bounds, {
                color: isSelected ? QUALITY_COLORS[quality] : '#3388ff',
                weight: isSelected ? 2 : 1,
                fillOpacity: isSelected ? 0.5 : 0,
                dashArray: isSelected ? '' : '5, 5'
            }).addTo(subtileLayer)
                .on('click', () => toggleSubtileSelection(subtileId, tile, latitude, longitude, row, col, tileId))
                .bindTooltip(`${tileId}.dds`, {
                    permanent: false,
                    direction: 'center',
                    className: 'subtile-tooltip'
                });

            subtileBounds.push({ subtileId, tileId, bounds, lat: subtileLat, lon: subtileLon });
        }
    }
}

function toggleSubtileSelection(subtileId, tile, latitude, longitude, row, col, tileId) {
    /** Toggle the selection state of a subtile. */
    const cols = Math.abs(latitude) > 22.5 ? 4 : 8;
    const stepLat = 0.125;
    const stepLon = 1.0 / cols;
    const subtileLat = latitude + row * stepLat;
    const subtileLon = longitude + col * stepLon;

    const index = selectedSubtiles.findIndex(s => s.subtileId === subtileId);
    if (index === -1) {
        selectedSubtiles.push({
            subtileId,
            tileId,
            tile,
            lat: subtileLat,
            lon: subtileLon,
            quality: '2',
            status: 'pending'
        });
        logMessage(`Subtile selected: ${subtileId} (${tileId}.dds)`);
        const bounds = [[subtileLat, subtileLon], [subtileLat + stepLat, subtileLon + stepLon]];
        const rectangle = L.rectangle(bounds, {
            color: QUALITY_COLORS['2'],
            backgroundColor: QUALITY_COLORS['2'],
            weight: 2,
            fillOpacity: 0.5
        }).addTo(subtileLayer);
        rectangle.on('click', () => toggleSubtileSelection(subtileId, tile, latitude, longitude, row, col, tileId));
    } else {
        selectedSubtiles.splice(index, 1);
        logMessage(`Subtile deselected: ${subtileId} (${tileId}.dds)`);
        subtileLayer.eachLayer(layer => {
            const layerBounds = layer.getBounds();
            if (layerBounds.getSouthWest().lat === subtileLat && layerBounds.getSouthWest().lng === subtileLon) {
                layer.setStyle({
                    color: '#3388ff',
                    weight: 1,
                    fillOpacity: 0,
                    dashArray: '5, 5'
                });
            }
        });
    }
    updateSubtilesList();
}

function updateSubtilesList() {
    /** Update the list of selected subtiles in the UI. */
    const subtilesList = document.getElementById('subtiles-list');
    const subtilesWindow = document.getElementById('subtiles-window');
    const downloadSubtilesButton = document.getElementById('download-subtiles-button');
    // Commented out: Element not referenced in the provided code or UI
    // const downloadbg = document.getElementById('download-subtiles-bg');

    if (!selectedSubtiles.length) {
        subtilesWindow.style.display = 'none';
        downloadSubtilesButton.style.display = 'none';
        subtilesList.innerHTML = '';
        return;
    }

    subtilesWindow.style.display = 'flex';
    downloadSubtilesButton.style.display = 'block';
    subtilesList.innerHTML = '';

    const [latitude] = parseTileName(selectedTiles[0]);
    const is2to1 = Math.abs(latitude) > 22.5;

    selectedSubtiles.forEach(subtile => {
        const div = document.createElement('div');
        div.className = 'subtile-item';
        const statusIcon = subtile.status === 'downloading'
            ? '<span class="status-icon"><i class="fas fa-spinner fa-spin"></i></span>'
            : subtile.status === 'completed'
            ? '<span class="status-icon"><i class="fas fa-check"></i></span>'
            : '';
        div.innerHTML = `
            <span>${subtile.tileId}.dds</span>
            <select onchange="updateSubtileQuality('${subtile.subtileId}', this.value)">
                <option value="5" ${subtile.quality === '5' ? 'selected' : ''}>Maximum (${is2to1 ? '16384x8192' : '16384x16384'})</option>
                <option value="4" ${subtile.quality === '4' ? 'selected' : ''}>High (${is2to1 ? '8192x4096' : '8192x8192'})</option>
                <option value="3" ${subtile.quality === '3' ? 'selected' : ''}>Medium (${is2to1 ? '4096x2048' : '4096x4096'})</option>
                <option value="2" ${subtile.quality === '2' ? 'selected' : ''}>Medium-Low (${is2to1 ? '2048x1024' : '2048x2048'})</option>
            </select>
            <div class="color-box" style="background-color: ${QUALITY_COLORS[subtile.quality]};"></div>
            ${statusIcon}
        `;
        subtilesList.appendChild(div);
    });
}

function updateSubtileStyle(subtileId, quality) {
    /** Update the visual style of a selected subtile. */
    const subtile = selectedSubtiles.find(s => s.subtileId === subtileId);
    if (subtile) {
        subtileLayer.eachLayer(layer => {
            const layerBounds = layer.getBounds();
            if (layerBounds.getSouthWest().lat === subtile.lat && layerBounds.getSouthWest().lng === subtile.lon) {
                layer.setStyle({
                    color: QUALITY_COLORS[quality],
                    backgroundColor: QUALITY_COLORS[quality],
                    weight: 2,
                    fillOpacity: 0.5,
                    dashArray: ''
                });
            }
        });
    }
}

function updateSubtileQuality(subtileId, quality) {
    /** Update the quality of a selected subtile. */
    const subtile = selectedSubtiles.find(s => s.subtileId === subtileId);
    if (subtile) {
        subtile.quality = quality;
        logMessage(`Subtile ${subtile.tileId}.dds quality changed to ${quality}`);
        updateSubtileStyle(subtileId, quality);
        updateSubtilesList();
    }
}

async function downloadSelectedTiles() {
    /** Download selected 1x1 tiles. */
    if (!selectedTiles.length) {
        logMessage('No tiles selected for download.');
        return;
    }
    if (isDownloading) {
        logMessage('Download already in progress.');
        return;
    }
    if (!outputPath || outputPath.trim() === '') {
        logMessage('Error: Output path cannot be empty.');
        return;
    }

    isDownloading = true;
    const downloadButton = document.getElementById('download-tiles-1x1');
    downloadButton.disabled = true;

    const cancelButtonContainer = document.getElementById('cancel-button-container');
    const cancelButton = document.createElement('button');
    cancelButton.id = 'cancel-download';
    cancelButton.textContent = 'Cancel Download';
    cancelButton.type = 'button';
    cancelButton.onclick = async () => {
        await cancelDownload();
        // Immediately stop the download loop
        isDownloading = false;
        downloadButton.textContent = 'Download 1x1 Tiles';
        downloadButton.disabled = false;
        cancelButtonContainer.innerHTML = '';
        logMessage('Download canceled.');
        await drawTiles([...Object.keys(drawnTiles), ...selectedTiles]);
        await reloadTiles();
    };
    cancelButtonContainer.appendChild(cancelButton);

    const quality = document.getElementById('quality-terrain').value;
    const converter = document.getElementById('converter').value;
    console.log(`Starting download with quality=${quality}, tiles=${selectedTiles}, outputPath=${outputPath}`);

    async function downloadNextTile(index) {
        if (index >= selectedTiles.length || !isDownloading) {
            isDownloading = false;
            downloadButton.textContent = 'Download 1x1 Tiles';
            downloadButton.disabled = false;
            cancelButtonContainer.innerHTML = '';
            logMessage('Download completed or canceled.');
            await drawTiles([...Object.keys(drawnTiles), ...selectedTiles]);
            await reloadTiles();
            return;
        }

        downloadButton.textContent = `Processing... ${index + 1}/${selectedTiles.length}`;
        const tile = selectedTiles[index];
        const [latitude, longitude] = parseTileName(tile);
        if (latitude === null || longitude === null) {
            logMessage(`Error: Invalid coordinates for tile ${tile}`);
            await downloadNextTile(index + 1);
            return;
        }

        console.log(`Sending request for tile ${tile}: lat=${latitude}, lon=${longitude}, quality=${quality}, outputPath=${outputPath}`);
        try {
            // Check isDownloading before making the fetch request
            if (!isDownloading) {
                logMessage(`Download canceled before processing tile ${tile}.`);
                return;
            }
            const response = await fetch('/api/download_tile', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: latitude,
                    lon: longitude,
                    quality_terrain: quality,
                    output_path: outputPath,
                    converter
                })
            });
            const data = await response.json();
            console.log(`Response for tile ${tile}:`, data);
            if (data.status === 'success') {
                logMessage(`Tile ${tile} (${generateFolderName(latitude, longitude)}): ${data.status}, quality=${data.quality}`);
                delete tileStatusCache[tile];
                await checkTileFolders([tile], async () => {
                    await drawTiles([tile], false);
                    if (isDownloading) {
                        await downloadNextTile(index + 1);
                    } else {
                        logMessage(`Download canceled after tile ${tile}.`);
                    }
                });
                reloadTiles();
            } else {
                logMessage(`Error downloading tile ${tile}: ${data.message}`);
                if (isDownloading) {
                    await downloadNextTile(index + 1);
                } else {
                    logMessage(`Download canceled after tile ${tile}.`);
                }
            }
        } catch (error) {
            logMessage(`Error downloading tile ${tile}: ${error}`);
            if (isDownloading) {
                await downloadNextTile(index + 1);
            } else {
                logMessage(`Download canceled after tile ${tile}.`);
            }
        }
    }

    downloadButton.textContent = `Processing... 1/${selectedTiles.length}`;
    await downloadNextTile(0);
}

async function downloadSelectedSubtiles() {
    /** Download selected subtiles. */
    if (!selectedSubtiles.length) {
        logMessage('No subtiles selected for download.');
        return;
    }
    if (isDownloading) {
        logMessage('Download already in progress.');
        return;
    }
    if (!outputPath || outputPath.trim() === '') {
        logMessage('Error: Output path cannot be empty.');
        return;
    }

    isDownloading = true;
    const downloadButton = document.getElementById('download-subtiles-button');
    downloadButton.textContent = 'Processing...';
    downloadButton.disabled = true;

    const cancelButtonContainer = document.getElementById('cancel-button-container');
    const cancelButton = document.createElement('button');
    cancelButton.id = 'cancel-download';
    cancelButton.textContent = 'Cancel Download';
    cancelButton.type = 'button';
    cancelButton.onclick = cancelDownload;
    cancelButtonContainer.appendChild(cancelButton);

    const converter = document.getElementById('converter').value;
    console.log(`Starting subtile download: ${JSON.stringify(selectedSubtiles)}, outputPath=${outputPath}`);
    

    async function downloadNextSubtile(index) {
        if (index >= selectedSubtiles.length || !isDownloading) {
            isDownloading = false;
            downloadButton.textContent = 'Download Subtiles';
            downloadButton.disabled = false;
            cancelButtonContainer.innerHTML = '';
            logMessage('Subtile download completed or canceled.');
            return;
        }

        const subtile = selectedSubtiles[index];
        subtile.status = 'downloading';
        updateSubtilesList();
        console.log(`Sending request for subtile ${subtile.subtileId}: lat=${subtile.lat}, lon=${subtile.lon}, quality=${subtile.quality}, outputPath=${outputPath}`);
        logMessage(`Downloading ${subtile.tileId}.`);  
        try {
            const response = await fetch('/api/download_subtile', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    lat: subtile.lat,
                    lon: subtile.lon,
                    quality: subtile.quality,
                    output_path: outputPath,
                    converter,
                    parent_tile: subtile.tile
                })
            });

            const data = await response.json();
            console.log(`Response for subtile ${subtile.subtileId}:`, data);
            if (data.status === 'success') {
                subtile.status = 'completed';
                delete tileStatusCache[subtile.tile];
                await checkTileFolders([subtile.tile], async () => {
                    await drawTiles([subtile.tile], false);
                    updateSubtilesList();
                    await downloadNextSubtile(index + 1);           
                });
                await reloadTiles();
            } else {
                subtile.status = 'pending';
                logMessage(`Error downloading subtile ${subtile.tileId}.dds: ${data.message}`);
                updateSubtilesList();
                await downloadNextSubtile(index + 1);
            }
        } catch (error) {
            subtile.status = 'pending';
            logMessage(`Error downloading subtile ${subtile.tileId}.dds: ${error}`);
            updateSubtilesList();
            await downloadNextSubtile(index + 1);
        }
    }

    
    updateSubtilesList();
    await downloadNextSubtile(0);
    await reloadTiles();
}

function enterSubtileMode() {
    /** Enter subtile selection mode for a single tile. */
    if (selectedTiles.length !== 1) {
        logMessage('Select exactly one tile for subtile mode.');
        return;
    }
    isSubtileMode = true;
    const tile = selectedTiles[0];
    const [latitude, longitude] = parseTileName(tile);
    logMessage(`Entering subtile mode for ${tile}`);
    drawSubtiles(tile, latitude, longitude);
    document.getElementById('download-tiles-1x1').disabled = true;
    document.getElementById('download-subtiles').textContent = 'Exit Subtile Mode';
    document.getElementById('quality-terrain').style.display = 'none';
    document.getElementById('quality_label').style.display = 'none';
    document.getElementById('download-tiles-1x1').style.display = 'none';
    drawTiles([...Object.keys(drawnTiles), ...selectedTiles], true);
    reloadTiles();
}

function exitSubtileMode() {
    /** Exit subtile selection mode. */
    isSubtileMode = false;
    subtileLayer.clearLayers();
    selectedSubtiles = [];
    updateSubtilesList();
    selectedTiles = [];
    document.getElementById('download-tiles-1x1').disabled = false;
    document.getElementById('download-subtiles').textContent = 'Select Subtiles';
    document.getElementById('quality-terrain').style.display = 'inherit';
    document.getElementById('quality_label').style.display = 'inherit';
    document.getElementById('download-tiles-1x1').style.display = 'inherit';
    updateSelectedTilesDisplay();
    drawTiles([...Object.keys(drawnTiles), ...selectedTiles], true);
    reloadTiles();
}

async function cancelDownload() {
    /** Cancel an ongoing download process. */
    try {
        const response = await fetch('/api/cancel_download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await response.json();
        logMessage(data.status === 'success' ? 'Download canceled successfully.' : `Error canceling download: ${data.message}`);
        isDownloading = false;
        const downloadButton = isSubtileMode
            ? document.getElementById('download-subtiles-button')
            : document.getElementById('download-tiles-1x1');
        downloadButton.textContent = isSubtileMode ? 'Select Subtiles' : 'Download 1x1 Tiles';
        downloadButton.disabled = false;
        const cancelButtonContainer = document.getElementById('cancel-button-container');
        cancelButtonContainer.innerHTML = '';
        await drawTiles([...Object.keys(drawnTiles), ...selectedTiles]);
        await reloadTiles();
        if (isSubtileMode) {
            const tile = selectedTiles[0];
            const [latitude, longitude] = parseTileName(tile);
            drawSubtiles(tile, latitude, longitude);
        }
    } catch (error) {
        logMessage(`Error canceling download: ${error}`);
        isDownloading = false;
        const downloadButton = isSubtileMode
            ? document.getElementById('download-subtiles-button')
            : document.getElementById('download-tiles-1x1');
        downloadButton.textContent = isSubtileMode ? 'Select Subtiles' : 'Download 1x1 Tiles';
        downloadButton.disabled = false;
        const cancelButtonContainer = document.getElementById('cancel-button-container');
        cancelButtonContainer.innerHTML = '';
        await drawTiles([...Object.keys(drawnTiles), ...selectedTiles]);
        await reloadTiles();
        if (isSubtileMode) {
            const tile = selectedTiles[0];
            const [latitude, longitude] = parseTileName(tile);
            drawSubtiles(tile, latitude, longitude);
        }
    }
}

function logMessage(message) {
    /** Log a message to the UI and console. */
    const log = document.getElementById('log');
    if (log) {
        log.innerHTML += `${message}<br>`;
        log.scrollTop = log.scrollHeight;
    } else {
        console.log('Log:', message);
    }
}

async function reloadTiles() {
    /** Reload all tiles and clear caches. */
    logMessage('Reloading tiles...');
    tileLayer.clearLayers();
    ddsLayer.clearLayers();
    window.tileLayers.forEach(layer => map.removeLayer(layer));
    window.tileLayers = [];
    drawnTiles = {};
    tileStatusCache = {};
    updateSubtilesList();
    await updateVisibleTiles();
}

async function updateVisibleTiles() {
    /** Update visible tiles based on map bounds. */
    const bounds = map.getBounds();
    const currentZoom = map.getZoom();
    const tiles = [];
    const latMin = Math.floor(bounds.getSouth());
    const latMax = Math.floor(bounds.getNorth());
    const lonMin = Math.floor(bounds.getWest());
    const lonMax = Math.floor(bounds.getEast());

    if (lastZoomLevel !== null &&
        ((lastZoomLevel < 7 && currentZoom >= 7) || (lastZoomLevel >= 7 && currentZoom < 7))) {
        console.log(`Zoom change detected: ${lastZoomLevel} -> ${currentZoom}, clearing cache`);
        tileLayer.clearLayers();
        ddsLayer.clearLayers();
        drawnTiles = {};
        window.tileLayers = [];
        if (isSubtileMode && selectedTiles.length === 1) {
            const tile = selectedTiles[0];
            const [latitude, longitude] = parseTileName(tile);
            drawSubtiles(tile, latitude, longitude);
        }
    }
    lastZoomLevel = currentZoom;

    for (let lat = latMin; lat <= latMax; lat++) {
        for (let lon = lonMin; lon <= lonMax; lon++) {
            const tile = lat < 0 ? `-${Math.abs(lat)}--${Math.abs(lon)}` : `${lat}-${lon}`;
            if (!drawnTiles[tile]) {
                tiles.push(tile);
            }
        }
    }

    if (tiles.length > 0) {
        await drawTiles([...Object.keys(drawnTiles), ...tiles, ...selectedTiles]);
    }
    await loadAirports();
}

map.on('moveend zoomend', async () => {
    await saveConfig();
    await updateVisibleTiles();
});

// Commented out: Initial call replaced by DOMContentLoaded to ensure DOM is ready
// updateVisibleTiles();
// loadAirports();

document.addEventListener('DOMContentLoaded', async () => {
    const removeButton = document.getElementById('remove-tiles');
    const downloadButton = document.getElementById('download-tiles-1x1');
    const downloadSubtilesButton = document.getElementById('download-subtiles');
    const downloadSubtilesConfirmButton = document.getElementById('download-subtiles-button');
    const searchBar = document.getElementById('search-bar');
    const toggleAirports = document.getElementById('toggle-airports');
    const reloadTilesButton = document.getElementById('reload-tiles');
    const outputPathInput = document.getElementById('output-path');
    const qualityTerrainSelect = document.getElementById('quality-terrain');
    const converterSelect = document.getElementById('converter');

    try {
        const response = await fetch('/api/load_config');
        const config = await response.json();
        console.log('Configuration loaded:', config);
        outputPath = config.output_path || outputPath;
        if (outputPathInput) {
            outputPathInput.value = outputPath;
        }
        if (qualityTerrainSelect) {
            qualityTerrainSelect.value = config.quality_terrain || '2';
        }
        if (converterSelect) {
            converterSelect.value = config.converter || 'imagemagick';
        }
        if (config.map_center && config.map_zoom) {
            map.setView([config.map_center.lat, config.map_center.lng], config.map_zoom);
        }
        // Load show_airports preference
        if (toggleAirports) {
            toggleAirports.checked = config.show_airports !== false; // Default to true if not set
            if (toggleAirports.checked) {
                map.addLayer(airportLayer);
                logMessage('Airports shown based on saved configuration.');
            } else {
                map.removeLayer(airportLayer);
                logMessage('Airports hidden based on saved configuration.');
            }
        }
        logMessage('Configuration loaded from server.');
    } catch (error) {
        console.error('Error loading configuration:', error);
        logMessage(`Error loading configuration: ${error}`);
    }

    if (outputPathInput) {
        outputPathInput.addEventListener('change', function () {
            outputPath = this.value.trim();
            if (!outputPath) {
                logMessage('Error: Output path cannot be empty. Reverting to default.');
                outputPath = 'C:\\Users\\Pc\\Documents\\Photoscenery';
                this.value = outputPath;
            }
            logMessage(`Output path updated to: ${outputPath}`);
            saveConfig();
        });
    } else {
        console.error('Input field output-path not found in DOM');
        logMessage('Error: Output path input field not found.');
    }

    if (qualityTerrainSelect) {
        qualityTerrainSelect.addEventListener('change', function () {
            logMessage(`Terrain quality changed to: ${this.value}`);
            saveConfig();
        });
    }

    if (converterSelect) {
        converterSelect.addEventListener('change', function () {
            logMessage(`Converter changed to: ${this.value}`);
            saveConfig();
        });
    }

    if (removeButton) {
        removeButton.addEventListener('click', removeSelectedTiles);
    }

    if (downloadButton) {
        downloadButton.addEventListener('click', downloadSelectedTiles);
    }

    if (downloadSubtilesButton) {
        downloadSubtilesButton.addEventListener('click', () => {
            if (isSubtileMode) {
                exitSubtileMode();
            } else {
                enterSubtileMode();
            }
        });
    }

    if (downloadSubtilesConfirmButton) {
        downloadSubtilesConfirmButton.addEventListener('click', downloadSelectedSubtiles);
    }

    if (searchBar) {
        searchBar.addEventListener('input', function () {
            updateSearchResults(this.value);
        });
    }

    if (toggleAirports) {
        toggleAirports.addEventListener('change', function () {
            if (this.checked) {
                map.addLayer(airportLayer);
                logMessage('Airports shown.');
            } else {
                map.removeLayer(airportLayer);
                logMessage('Airports hidden.');
            }
            saveConfig(); // Save the new state
        });
    }

    if (reloadTilesButton) {
        reloadTilesButton.addEventListener('click', reloadTiles);
    }

    // Initial load of tiles and airports
    await updateVisibleTiles();
    await loadAirports();
});

// Layer control for toggling map layers
const baseMaps = {
    "Satellite Imagery": esriWorldImagery,
    "Labels": esriWorldTransportation
};

const overlayMaps = {
    "1x1 Tiles": tileLayer,
    "DDS Subtiles": ddsLayer,
    "Subtile Selection": subtileLayer,
    "Airports": airportLayer
};

L.control.layers(baseMaps, overlayMaps).addTo(map);

// Ensure configuration is saved on window close
window.addEventListener('beforeunload', saveConfig);