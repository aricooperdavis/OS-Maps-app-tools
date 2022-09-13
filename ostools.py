#!/usr/bin/env python3

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
    no_conversion = False
except ImportError:
    print('Warning: unable to import PIL (Image) - convert unavailable.')
    no_conversion = True

try:
    import requests
    no_update = False
except ImportError:
    # print('Warning: unable to import requests - update unavailable.')
    no_update = True 

# Parse args
parser = argparse.ArgumentParser(description='Tools for working with maps from the OS Maps app.')
parser.add_argument('-verbose', action='store_true', dest='v', help='run in verbose mode')
subparsers = parser.add_subparsers(required=True, dest='command', metavar='command') 

extract_parser = subparsers.add_parser('extract', help='Extract maps from mbgl-offline.db')
extract_parser.add_argument('-file', type=str, default='./mbgl-offline.db', help='path to OS Maps database (default: \'%(default)s\')')
extract_parser.add_argument('-regions', nargs='*', type=str, help='only extract REGIONS')
extract_parser.add_argument('-zoom', type=int, default=16, help='tile zoom level (default: %(default)s)')

if not no_conversion:
    convert_parser = subparsers.add_parser('convert', help='Convert MBTiles files from png to webp')
    convert_parser.add_argument('file', type=str, help='path to MBTiles file')
    convert_parser.add_argument('-quality', type=int, default=50, help='quality of WEBP compression (1-100, default: %(default)s)')

if not no_update:
    update_parser = subparsers.add_parser('update')
    update_parser.add_argument('file', type=str, help='path to MBTiles file')
    update_parser.add_argument('-container', type=str, default='2021-12', help='update container (default: \'%(default)s)\'')
    update_parser.add_argument('-delay', type=float, default=1.0, help='seconds delay between tile-server requests (default: %(default)s)')

args = parser.parse_args()

# Extract
if args.command == 'extract':

    # Parse db
    if args.v: print(f'Loading OS Maps database \'{args.file}\': ', end='', flush=True)
    in_db = sqlite3.connect(args.file)
    in_cur = in_db.cursor()
    if args.v: print('Done')

    if args.v: print('Identifying regions: ', end='', flush=True)
    REGIONS = {}
    for [r, df, ds] in in_cur.execute('SELECT * FROM regions WHERE description IS NOT NULL'):
        REGIONS[r] = {
            'FNAME': ds.decode('utf-8').split('-')[0].strip(),
            'NAME': ds.decode('utf-8'),
            'BOUNDS': ','.join(map(str, [json.loads(df)['bounds'][i] for i in [1,0,3,2]])),
            'MINZOOM': str(math.floor(json.loads(df)['min_zoom'])),
            'MAXZOOM': str(math.floor(json.loads(df)['max_zoom'])),
        }
    if args.v: print(', '.join([REGIONS[R]["FNAME"] for R in REGIONS]))

    for R in REGIONS:
        # Only process regions specified
        if args.regions:
            if not REGIONS[R]['FNAME'] in args.regions: continue

        # Setup DB
        if args.v: print(f'Creating outfile \'{REGIONS[R]["FNAME"]}.mbtiles\': ', end='', flush=True)
        out_db = sqlite3.connect(REGIONS[R]['FNAME']+'.mbtiles')
        out_cur = out_db.cursor()
        if args.v: print('Done')
        
        if args.v: print('Preparing MBTiles structure: ', end='', flush=True)
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
        ''', [REGIONS[R]['NAME'], REGIONS[R]['BOUNDS'], REGIONS[R]['MINZOOM'], REGIONS[R]['MAXZOOM']])
        
        # Create tiles table
        # https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#schema-1
        out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
        if args.v: print('Done')

        if args.v: print('Decompressing and copying map tiles: ', end='', flush=True)
        # Parse and decompress tiles
        for [z, x, y, data] in in_cur.execute('''SELECT z, x, y, data 
            FROM tiles
            INNER JOIN region_tiles
            ON region_tiles.tile_id == tiles.id
            WHERE region_tiles.region_id == ?
            AND tiles.z == ?
        ''', [R, args.zoom]):

            out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, math.floor((2**z)-1-y), zlib.decompress(data)])
        if args.v: print('Done')

        # Close db
        out_db.commit()
        out_db.close()

    in_db.commit()
    in_db.close()
    if args.v: print('Extract completed.')

# Convert
elif args.command == 'convert':

    # Load/create DBs
    if args.v: print(f'Loading MBTiles file \'{args.file}\': ', end='', flush=True)
    in_db = sqlite3.connect(args.file)
    in_cur = in_db.cursor()
    if args.v: print('Done')
    if args.v: print(f'Creating outfile \'{args.file[:-8]}_webp.mbtiles\': ', end='', flush=True)
    out_db = sqlite3.connect(args.file[:-8]+'_webp.mbtiles')
    out_cur = out_db.cursor()
    if args.v: print('Done')

    # Prepare output DB
    if args.v: print('Preparing MBTiles structure: ', end='', flush=True)
    out_cur.execute('PRAGMA application_id = 1297105496')
    out_cur.execute('CREATE TABLE metadata (name text, value text)')
    for [n, v] in in_cur.execute('SELECT name, value FROM metadata'):
        if n == 'format':
            v = 'webp'
        out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [n, v])
    out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
    if args.v: print('Done')

    # Converting tiles to webp
    if args.v: print('Converting tiles to WEBP (be patient!): ', end='', flush=True)
    for [z, x, y, png] in in_cur.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'):
        webp = io.BytesIO()
        Image.open(io.BytesIO(png)).save(webp, format='webp', method=6, quality=args.quality)
        out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, webp.getvalue()])
    if args.v: print('Done')

    in_db.commit()
    in_db.close()
    out_db.commit()
    out_db.close()
    if args.v: print('Convert completed.')

# Update
elif args.command == 'update':
    if input('This scrapes tiles from OS Servers, which is antisocial, slow, and probably prohibited. Are you sure you want to continue? (Y/N): ').strip().upper() == 'Y':
        
        # Load/create DBs
        if args.v: print(f'Loading MBTiles file \'{args.file}\': ', end='', flush=True)
        in_db = sqlite3.connect(args.file)
        in_cur = in_db.cursor()
        if args.v: print('Done')
        if args.v: print(f'Creating outfile \'{args.file[:-8]}_{args.container}.mbtiles\': ', end='', flush=True)
        out_db = sqlite3.connect(f'{args.file[:-8]}_{args.container}.mbtiles')
        out_cur = out_db.cursor()
        if args.v: print('Done')

        # Prepare output DB
        if args.v: print('Preparing MBTiles structure: ', end='', flush=True)
        out_cur.execute('PRAGMA application_id = 1297105496')
        out_cur.execute('CREATE TABLE metadata (name text, value text)')
        for [n, v] in in_cur.execute('SELECT name, value FROM metadata'):
            if n == 'name':
                v = v[:-7]+args.container.replace('-','/')
            out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [n, v])
        out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')
        if args.v: print('Done')

        # Update tiles from OS Servers
        if args.v: print('Updating tiles from OS Servers (be patient!): ', end='', flush=True)
        flip_y = lambda y: math.floor((2**16)-y-1) # https://gist.github.com/tmcw/4954720
        for [z, x, y] in in_cur.execute('SELECT zoom_level, tile_column, tile_row FROM tiles'):
            if not out_cur.execute('SELECT count(*) FROM tiles WHERE zoom_level == ? AND tile_column == ? AND tile_row == ?', [z, x, y]).fetchone()[0]:
                time.sleep(args.delay) # No DOSing OS please!
                _r = requests.get(f'https://tiles.leisure.maps.osinfra.net/{args.container}/1_25k/{z}/{x}/{flip_y(y)}.png')
                out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, _r.content])
        if args.v: print('Done')

        in_db.commit()
        in_db.close()
        out_db.commit()
        out_db.close()
        if args.v: print('Update completed.')