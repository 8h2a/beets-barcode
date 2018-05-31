# beets-barcode

A plugin for beets that finds releases based on a barcodes that are provided 
via text or decoded from image files.

This plugin searches all image files for barcodes to help in selecting the
correct release. It's also possible to manually enter a barcode number or
catalogue number.

If it finds a barcode, it gets the release-id from musicbrainz and
penalizes releases which don't correspond to the found barcode(s).
Whenever it finds a barcode, it will print a helpful message, before the
candidates are shown, to help understanding which candidate corresponds to
a barcode that was found.

## Installation
You can install the plugin by using these commands:
```
git clone https://github.com/8h2a/beets-barcode.git
cd beets-barcode
python setup.py install
```
Additionally you might need to install zbar seperately.
See [pyzbar](https://github.com/NaturalHistoryMuseum/pyzbar#installation) 
for instructions.

You can then [enable the plugin in beet's config.yaml](https://beets.readthedocs.io/en/latest/plugins/index.html#using-plugins):
```yaml
plugins: barcode
```
