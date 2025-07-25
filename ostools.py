#!/usr/bin/env python3

"""
Python tools for extracting and converting maps from the OS Maps app.
"""

# Imports
import argparse
import io
import json
import math
import sqlite3
import time
import zlib

try:
    from PIL import Image
    NO_CONVERSION = False
except ImportError:
    print('Warning: unable to import PIL (Image) - convert unavailable.')
    NO_CONVERSION = True

try:
    import requests
    NO_UPDATE = False
except ImportError:
    # print('Warning: unable to import requests - update unavailable.')
    NO_UPDATE = True

def parse_args(no_conversion, no_update):
    """
    Parse command line arguments.
    """

    parser = argparse.ArgumentParser(description='Tools for working with maps from the OS Maps app.')
    parser.add_argument('-verbose', action='store_true', help='run in verbose mode')
    subparsers = parser.add_subparsers(required=True, dest='command', metavar='command')

    extract_parser = subparsers.add_parser('extract', help='Extract maps from map_data.db and customOfflineMaps.db files')
    extract_parser.add_argument('-tiledb', default='./map_data.db', help='path to tile database (default: \'%(default)s\')')
    extract_parser.add_argument('-infodb', default='./customOfflineMaps.db', help='path to info database (default: \'%(default)s\')')
    extract_parser.add_argument('-regions', nargs='*', help='regions to extract from the database')
    extract_parser.add_argument('-zoom', type=int, default=16, help='MBTiles tile zoom level (default: %(default)s)')

    if not no_conversion:
        convert_parser = subparsers.add_parser('convert', help='Convert MBTiles files from png to webp')
        convert_parser.add_argument('file', help='path to MBTiles file')
        convert_parser.add_argument('-quality', type=int, default=50, help='quality of WEBP compression (1-100, default: %(default)s)')

    dedupe_parser = subparsers.add_parser('dedupe', help='Dedupe tiles from overlapping MBTiles files')
    dedupe_parser.add_argument('file1', help='path to MBTile to dedupe (in place)')
    dedupe_parser.add_argument('file2', help='path to MBTile to compare against')

    if not no_update:
        update_parser = subparsers.add_parser('update')
        update_parser.add_argument('file', help='path to MBTiles file')
        update_parser.add_argument('-container', type=str, default='2023-06', help='update container (default: \'%(default)s)\'')
        update_parser.add_argument('-delay', type=float, default=1.0, help='seconds delay between tile-server requests (default: %(default)s)')

    return parser.parse_args()

def flip_y(y, z=16):
    """
    Convert between XYZ and TMS notation for y coords
    https://gist.github.com/tmcw/4954720
    """
    return math.floor((2**z)-y-1)

def extract(tiledb, infodb, rois, zoom, verbose):
    """
    Extract maps in MBTiles format from a map_data.db file and label it using data from a customOfflineMaps.db file.
    """

    # Parse db
    if verbose: print(f'Loading \'{infodb}\': ', end='', flush=True)
    in_db = sqlite3.connect(infodb)
    in_cur = in_db.cursor()
    if verbose: print('Done')

    if verbose: print('Identifying regions: ', end='', flush=True)
    regions = {}
    for [r_id, r_mn, r_ln, r_ls, r_le, r_lw, r_zn, r_zx] in in_cur.execute('SELECT correlated_id, map_name, latitude_north, latitude_south, longitude_east, longitude_west, zoom_min, zoom_max FROM offline_maps WHERE map_name IS NOT NULL'):
        regions[r_id] = {
            'FNAME': r_mn.split('-')[0].strip(),
            'NAME': r_mn,
            'BOUNDS': ','.join(map(str,[r_lw, r_ls, r_le, r_ln])),
            'MINZOOM': str(math.floor(r_zn)),
            'MAXZOOM': str(math.floor(r_zx)),
        }
    if verbose: print(', '.join([region["FNAME"] for _, region in regions.items()]))

    if verbose: print(f'Closing \'{infodb}\': ', end='', flush=True)
    in_db.commit()
    in_db.close()
    if verbose: print('Done')

    if verbose: print(f'Loading \'{tiledb}\': ', end='', flush=True)
    in_db = sqlite3.connect(tiledb)
    in_cur = in_db.cursor()
    if verbose: print('Done')

    for r_id, region in regions.items():
        # Only process regions specified
        if rois:
            if not region['FNAME'] in rois: continue

        # Setup DB
        if verbose: print(f'Creating outfile \'{region["FNAME"]}.mbtiles\': ', end='', flush=True)
        out_db = sqlite3.connect(region['FNAME']+'.mbtiles')
        out_cur = out_db.cursor()
        if verbose: print('Done')

        if verbose: print('Preparing MBTiles structure: ', end='', flush=True)
        # Set MBTiles magic number
        # https://www.sqlite.org/src/artifact?ci=trunk&filename=magic.txt
        out_cur.execute('PRAGMA application_id = 1297105496')

        # Create metadata table
        # https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#schema
        out_cur.execute('CREATE TABLE metadata (name text, value text)')

        # Populate metadata
        # https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#content
        out_cur.execute('''INSERT INTO metadata VALUES
            ("name", ?),
            ("format", "png"),
            ("bounds", ?),
            ("center", ""),
            ("minzoom", ?),
            ("maxzoom", ?),
            ("type", "baselayer");
        ''', [region['NAME'], region['BOUNDS'], region['MINZOOM'], region['MAXZOOM']])

        # Create tiles table
        # https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#schema-1
        out_cur.execute('''CREATE TABLE tiles (
            zoom_level integer,
            tile_column integer,
            tile_row integer,
            tile_data blob
        )''')
        if verbose: print('Done')

        if verbose: print('Decompressing and copying map tiles: ', end='', flush=True)
        # Parse and decompress tiles
        for [z, x, y, data] in in_cur.execute('''SELECT z, x, y, data
            FROM tiles
            INNER JOIN region_tiles
            ON region_tiles.tile_id == tiles.id
            WHERE region_tiles.region_id == ?
            AND tiles.z == ?
        ''', [r_id, zoom]):

            out_cur.execute(
                'INSERT INTO tiles VALUES (?, ?, ?, ?)',
                [z, x, flip_y(y, z), zlib.decompress(data)]
            )
        if verbose: print('Done')

        # Close db
        if verbose: print(f'Closing \'{region["FNAME"]}.mbtiles\': ', end='', flush=True)
        out_db.commit()
        out_db.close()
        if verbose: print('Done')

    in_db.commit()
    in_db.close()
    if verbose: print('Extract completed.')
    return True

def convert(file, quality, verbose):
    """
    Convert tiles within an MBTiles file from PNG to WEBP format.
    """
    # Load/create DBs
    if verbose: print(f'Loading MBTiles file \'{file}\': ', end='', flush=True)
    in_db = sqlite3.connect(file)
    in_cur = in_db.cursor()
    if verbose: print('Done')
    if verbose: print(f'Creating outfile \'{file[:-8]}_webp.mbtiles\': ', end='', flush=True)
    out_db = sqlite3.connect(file[:-8]+'_webp.mbtiles')
    out_cur = out_db.cursor()
    if verbose: print('Done')

    # Prepare output DB
    if verbose: print('Preparing MBTiles structure: ', end='', flush=True)
    out_cur.execute('PRAGMA application_id = 1297105496')
    out_cur.execute('CREATE TABLE metadata (name text, value text)')
    for [name, value] in in_cur.execute('SELECT name, value FROM metadata'):
        if name == 'format':
            value = 'webp'
        out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [name, value])
    out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
    if verbose: print('Done')

    # Converting tiles to webp
    if verbose: print('Converting tiles to WEBP (be patient!): ', end='', flush=True)
    for [z, x, y, png] in in_cur.execute(
            'SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'
        ):
        webp = io.BytesIO()
        Image.open(io.BytesIO(png)).save(webp, format='webp', method=6, quality=quality)
        out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, webp.getvalue()])
    if verbose: print('Done')

    # Close DBs
    if verbose: print(f'Closing \'{file}.mbtiles\': ', end='', flush=True)
    in_db.commit()
    in_db.close()
    if verbose: print('Done')
    # Close db
    if verbose: print(f'Closing \'{file[:-8]}_webp.mbtiles\': ', end='', flush=True)
    out_db.commit()
    out_db.close()
    if verbose: print('Done')
    if verbose: print('Convert completed.')
    return True

def dedupe(file1, file2, verbose):
    """
    Remove (in place) duplicated tiles from overlapping MBTiles files.
    """
    if verbose: print('Loading databases: ', end='', flush=True)
    # Load file to dedupe
    dd_db = sqlite3.connect(file1)
    dd_cur = dd_db.cursor()

    # Attach comparison file
    dd_cur.execute('ATTACH ? AS cp_db', [file2])
    if verbose: print('Done')

    # Dedupe
    if verbose: print(f'Removing tiles from \'{file1}\' that appear in \'{file2}\': ', end='', flush=True)
    dd_cur.execute('''DELETE FROM main.tiles
        WHERE main.tiles.ROWID IN (
            SELECT main.tiles.ROWID FROM main.tiles
            INNER JOIN cp_db.tiles ON (
                main.tiles.tile_column = cp_db.tiles.tile_column
                AND main.tiles.tile_row = cp_db.tiles.tile_row
                AND main.tiles.zoom_level = cp_db.tiles.zoom_level
            )
        )''')

    dupes = dd_cur.rowcount
    if verbose: print(f'{dupes} duplicates')

    # Close DBs
    dd_db.commit()
    if dupes > 0:
        if verbose: print('Resizing MBTiles database: ', end='', flush=True)
        dd_cur.execute('VACUUM')
        if verbose: print('Done')
    dd_db.close()
    if verbose: print('Dedupe completed.')

    return True

def update(file, delay, container, verbose):
    """
    Update an MBTiles map from OS servers.
    """
    # Load/create DBs
    if verbose: print(f'Loading MBTiles file \'{file}\': ', end='', flush=True)
    in_db = sqlite3.connect(file)
    in_cur = in_db.cursor()
    if verbose: print('Done')
    if verbose: print(f'Creating outfile \'{file[:-8]}_{container}.mbtiles\': ', end='', flush=True)
    out_db = sqlite3.connect(f'{file[:-8]}_{container}.mbtiles')
    out_cur = out_db.cursor()
    if verbose: print('Done')

    # Prepare output DB
    if verbose: print('Preparing MBTiles structure: ', end='', flush=True)
    out_cur.execute('PRAGMA application_id = 1297105496')
    out_cur.execute('CREATE TABLE metadata (name text, value text)')
    for [name, value] in in_cur.execute('SELECT name, value FROM metadata'):
        if name == 'name':
            value = value[:-7]+container.replace('-','/')
        if name == 'format':
            value = 'png'
        out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [name, value])
    out_cur.execute('''CREATE TABLE tiles (
        zoom_level integer,
        tile_column integer,
        tile_row integer,
        tile_data blob
    )''')
    if verbose: print('Done')

    # Update tiles from OS Servers
    if verbose: print('Updating tiles from OS Servers (be patient!): ', end='', flush=True)
    for [z, x, y] in in_cur.execute('SELECT zoom_level, tile_column, tile_row FROM tiles'):
        if not out_cur.execute('SELECT count(*) FROM tiles WHERE zoom_level == ? AND tile_column == ? AND tile_row == ?', [z, x, y]).fetchone()[0]:
            time.sleep(delay) # No DOSing OS please!
            _r = requests.get(f'https://tiles.leisure.maps.osinfra.net/{container}/1_25k/{z}/{x}/{flip_y(y)}.png')
            out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, _r.content])
    if verbose: print('Done')

    in_db.commit()
    in_db.close()
    out_db.commit()
    out_db.close()
    if verbose: print('Update completed.')
    return True

if __name__ == '__main__':
    ARGS = parse_args(NO_CONVERSION, NO_UPDATE)
    if ARGS.command == 'extract':
        extract(ARGS.tiledb, ARGS.infodb, ARGS.regions, ARGS.zoom, ARGS.verbose)
    elif ARGS.command == 'convert':
        convert(ARGS.file, ARGS.quality, ARGS.verbose)
    elif ARGS.command == 'dedupe':
        dedupe(ARGS.file1, ARGS.file2, ARGS.verbose)
    elif ARGS.command == 'update':
        if input('This scrapes tiles from OS Servers, which is antisocial, slow, and probably prohibited. Are you sure you want to continue? (Y/N): ').strip().upper() == 'Y':
            update(ARGS.file, ARGS.delay, ARGS.container, ARGS.verbose)
