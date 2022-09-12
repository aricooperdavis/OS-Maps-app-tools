#!/usr/bin/env python3

import argparse
import io
import math
from PIL import Image
import requests
import sqlite3

# Parse args
parser = argparse.ArgumentParser(description='Convert MBTiles file format from png to webp.')
parser.add_argument('file', help='Path to the file to convert.')
args = parser.parse_args()
DB = args.file

# Parse db
in_db = sqlite3.connect(DB)
in_cur = in_db.cursor()
out_db = sqlite3.connect(DB)
out_cur = out_db.cursor(DB[:-8]+'_webp.mbtiles')

# Set MBTiles magic number
# https://www.sqlite.org/src/artifact?ci=trunk&filename=magic.txt
out_cur.execute('PRAGMA application_id = 1297105496')
# Create metadata
# https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#schema
out_cur.execute('CREATE TABLE metadata (name text, value text)')
# Populate metadata
# https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#content
for [n, v] in in_cur.execute('SELECT name, value FROM metadata'):
    if n == 'format':
        v = 'webp'
    out_cur.execute('INSERT INTO metadata VALUES (?, ?)', [n, v])

# Create tiles
# https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md#schema-1
out_cur.execute('CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)')

# Parse and decompress tiles
for [z, x, y, png] in in_cur.execute('SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles'):
    webp = io.BytesIO()
    Image.open(io.BytesIO(png)).save(webp, format='webp', method=6, quality=50)
    out_cur.execute('INSERT INTO tiles VALUES (?, ?, ?, ?)', [z, x, y, webp.getvalue()])

in_db.commit()
in_db.close()
out_db.commit()
out_db.close()
