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

    extract_parser = subparsers.add_parser('extract', help='Extract maps from mbgl-offline.db')
    extract_parser.add_argument('-file', type=str, default='./mbgl-offline.db', help='path to OS Maps database (default: \'%(default)s\')')
    extract_parser.add_argument('-regions', nargs='*', type=str, help='regions to extract from the database')
    extract_parser.add_argument('-zoom', type=int, default=16, help='MBTiles tile zoom level (default: %(default)s)')

    if not no_conversion:
        convert_parser = subparsers.add_parser('convert', help='Convert MBTiles files from png to webp')
        convert_parser.add_argument('file', type=str, help='path to MBTiles file')
        convert_parser.add_argument('-quality', type=int, default=50, help='quality of WEBP compression (1-100, default: %(default)s)')

    if not no_update:
        update_parser = subparsers.add_parser('update')
        update_parser.add_argument('file', type=str, help='path to MBTiles file')
        update_parser.add_argument('-container', type=str, default='2021-12', help='update container (default: \'%(default)s)\'')
        update_parser.add_argument('-delay', type=float, default=1.0, help='seconds delay between tile-server requests (default: %(default)s)')

    return parser.parse_args()

def extract(file, rois, zoom, verbose):
    """
    Extract maps in MBTiles format from an OS Maps app mbgl-offline.db database.
    """

    # Parse db
    if verbose: print(f'Loading OS Maps database \'{file}\': ', end='', flush=True)
    in_db = sqlite3.connect(file)
    in_cur = in_db.cursor()
    if verbose: print('Done')

    if verbose: print('Identifying regions: ', end='', flush=True)
    regions = {}
    for [r_id, r_df, r_ds] in in_cur.execute('SELECT * FROM regions WHERE description IS NOT NULL'):
        regions[r_id] = {
            'FNAME': r_ds.decode('utf-8').split('-')[0].strip(),
            'NAME': r_ds.decode('utf-8'),
            'BOUNDS': ','.join(map(str, [json.loads(r_df)['bounds'][i] for i in [1,0,3,2]])),
            'MINZOOM': str(math.floor(json.loads(r_df)['min_zoom'])),
            'MAXZOOM': str(math.floor(json.loads(r_df)['max_zoom'])),
        }
    if verbose: print(', '.join([region["FNAME"] for _, region in regions.items()]))

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
        out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
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

            out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, math.floor((2**z)-1-y), zlib.decompress(data)])
        if verbose: print('Done')

        # Close db
        out_db.commit()
        out_db.close()

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
    for [z, x, y, png] in in_cur.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'):
        webp = io.BytesIO()
        Image.open(io.BytesIO(png)).save(webp, format='webp', method=6, quality=quality)
        out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, webp.getvalue()])
    if verbose: print('Done')

    in_db.commit()
    in_db.close()
    out_db.commit()
    out_db.close()
    if verbose: print('Convert completed.')
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
        out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [name, value])
    out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
    if verbose: print('Done')

    # Update tiles from OS Servers
    def flip_y(y):
        """
        https://gist.github.com/tmcw/4954720
        """
        return math.floor((2**16)-y-1)

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
        extract(ARGS.file, ARGS.regions, ARGS.zoom, ARGS.verbose)
    elif ARGS.command == 'convert':
        convert(ARGS.file, ARGS.quality, ARGS.verbose)
    elif ARGS.command == 'update':
        if input('This scrapes tiles from OS Servers, which is antisocial, slow, and probably prohibited. Are you sure you want to continue? (Y/N): ').strip().upper() == 'Y':
            update(ARGS.file, ARGS.container, ARGS.delay, ARGS.verbose)
