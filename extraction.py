#!/usr/bin/env python3

import json
import math
import sqlite3
import zlib

DB = 'mbgl-offline.db' # Name of file to convert
ZL = 16 # Desired zoom level

# Parse db
in_db = sqlite3.connect(DB)
in_cur = in_db.cursor()

REGIONS = {}
for [r, df, ds] in in_cur.execute('SELECT * FROM regions WHERE description IS NOT NULL'):
    REGIONS[r] = {
        'FNAME': ds.decode('utf-8').split('-')[0].strip(),
        'NAME': ds.decode('utf-8'),
        'BOUNDS': ','.join(map(str, [json.loads(df)['bounds'][i] for i in [1,0,3,2]])),
        'MINZOOM': str(math.floor(json.loads(df)['min_zoom'])),
        'MAXZOOM': str(math.floor(json.loads(df)['max_zoom'])),
    }

for R in REGIONS:    
    # Setup DB
    out_db = sqlite3.connect(REGIONS[R]['FNAME']+'.mbtiles')
    out_cur = out_db.cursor()
    
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
    
    # Parse and decompress tiles
    for [z, x, y, data] in in_cur.execute('''SELECT z, x, y, data 
        FROM tiles
        INNER JOIN region_tiles
        ON region_tiles.tile_id == tiles.id
        WHERE region_tiles.region_id == ?
        AND tiles.z == ?
    ''', [R, ZL]):

        out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, math.floor((2**z)-1-y), zlib.decompress(data)])
    
    # Close db
    out_db.commit()
    out_db.close()

in_db.commit()
in_db.close()
