# OS Maps app tools
Extracting and converting maps from the OS Maps app.

## Summary
* Paper Ordnance Survey maps come with a code that allow you to add the maps you've bought to your OS Account.
* In the [OS Maps app](https://shop.ordnancesurvey.co.uk/apps/os-maps-subscriptions/#app) you can download the maps in your account without the need for a subscription.
* This repository contains tools that facilitate extracting maps from the OS Maps app in MBTiles format and converting the tiles from the default `.png` to the more space efficient `.webp`.
* This allows you to use the digital OS Maps that you've bought with other mapping apps.

## :warning:Disclaimer
This repository contains no intellectual property belonging to Ordnance Survey. The tools and techniques described should only be used in accordance with the Ordance Survey terms of use and UK law. Be aware that these terms of service may explicitly prohibit the extraction of maps from the app. 

Please don't share any OS Maps - purchasing their excellent maps funds the work put into making them.

## Directions for use
_You'll need a rooted device to extract maps from the OS App. If you don't have a physical rooted device then you can use the emulator built into the Android Studio SDK with a rooted virtual device._

### Extracting maps
Directions for extracting the maps downloaded in the OS Maps app to individual MBTiles files

1. Within the OS Maps app, [download the maps](https://osmaps.com/os-maps-help?categoryId=631349&article=637593#article-id-637593) that you want to extract
1. Copy `/data/data/uk.co.ordnancesurvey.osmaps/files/mbgl-offline.db` to your computer
1. Run `extraction.py`

### Converting maps
Directions for converting the tiles within the extracted maps to webp format for more space efficient storage. This can be a _lossy_ process so you may want to tweak the hardcoded [compression parameters](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#webp) to your quality/size preferences.

1. Run `conversion.py $filename`
