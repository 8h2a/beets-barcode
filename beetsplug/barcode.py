from beets.plugins import BeetsPlugin
from beets.ui.commands import PromptChoice
from beets.mediafile import TYPES
import musicbrainzngs
import os
import os.path

from PIL import Image
from pyzbar.pyzbar import decode
from pyzbar.pyzbar import ZBarSymbol

# TODO get rid of these in the future, because interal non-plugin-API:
from beets.ui.commands import disambig_string
from beets.autotag import mb

"""
requirements:
sudo apt-get install libzbar0
pip install pyzbar Pillow
+ beets exact same version because i use internal stuff :(

limitations:
    * heavy use of interal beets functions which may change any day

TODO:
    * proper beetsplug thingy so it can be installed easier
    * release (pip, installation instructions)?
    * settings (extensions (tiff,bmp,etc), verbosity, path stuff?)
    * maybe beets.ui.get_path_formats (see beets-copyartifacts)
"""


# utility function
def _get_files(paths, types):
    files = []
    for path in paths:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    # try-except because [1] and [1:] can fail
                    file_ext = os.path.splitext(filename)[1].decode('utf8')[1:]
                    full_path = os.path.join(dirpath, filename)
                    if file_ext in types and full_path not in files:
                        files.append(full_path)
                except:
                    pass
    return files


class Barcode(BeetsPlugin):
    def __init__(self):
        super(Barcode, self).__init__()

    def candidates(self, items, artist, album, va_likely):
        # TODO move to self object thing and setup during setup
        types_pictures = ("jpg", "jpeg", "png")
        types_barcodes = [ZBarSymbol.EAN13,
                          ZBarSymbol.ISBN10,
                          ZBarSymbol.ISBN13,
                          ZBarSymbol.UPCA,
                          ZBarSymbol.UPCE]

        paths = []
        # get paths from music tracks
        for i in items:
            path = os.path.dirname(i.path)
            if path not in paths:
                paths.append(path)

        # append parent paths (if they dont contain more (other) media files
        # other than those we already know about)
        def _path_is_probably_ok(path, items):
            return len(_get_files([path], TYPES)) <= len(items)

        parent_paths = []
        for path in paths:
            parentdir = os.path.dirname(path)
            if _path_is_probably_ok(parentdir, items) \
               and parentdir not in paths \
               and parentdir not in parent_paths:
                parent_paths.append(parentdir)
        paths.extend(parent_paths)

        # get pictures from paths
        files_to_decode = _get_files(paths, types_pictures)

        # decode all pictures to find barcodes
        barcodes = []
        for filepath in files_to_decode:
            try:
                # TODO barcodes.extend() + map results to .data
                results = decode(Image.open(filepath), types_barcodes)
                for r in results:
                    if r.data not in barcodes:
                        barcodes.append(r.data)
            except:
                pass

        # convert barcodes to releases using musicbrainz search
        releases = ()
        if len(barcodes) > 0:
            print("Found the following barcodes: {}".format(barcodes))

        for barcode in barcodes:
            try:
                res = musicbrainzngs.search_releases(barcode=barcode, limit=30)
                for release in res['release-list']:
                    albuminfo = mb.album_for_id(release['id'])
                    print("{} => {} https://musicbrainz.org/release/{}".format(
                        barcode,
                        disambig_string(albuminfo),
                        release['id']
                    ))
                    releases.append(albuminfo)
            except:
                pass
        return releases

    """
    TODO description
    manually enter barcode and search on musicbrainz
    """
    def album_for_id(self, album_id):
        try:
            res = musicbrainzngs.search_releases(barcode=album_id, limit=30)
        except:
            return None

        for release in res['release-list']:
            try:
                print(u"{}, {}, {}, {}, {}, {}, {}{}".format(
                    release['title'],
                    release['date'],
                    release['medium-track-count'],
                    release['medium-list'][0]['format'],
                    release['label-info-list'][0]['catalog-number'],
                    release['country'],
                    "https://musicbrainz.org/release/",
                    release['id'],
                ))
            except:
                pass

        if len(res['release-list']) == 1:
            # once we have an ID, use the internal beets musicbrainz thing:
            try:
                return mb.album_for_id(res['release-list'][0]['id'])
            except:
                pass

        return None
