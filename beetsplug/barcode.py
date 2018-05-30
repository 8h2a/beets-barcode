from beets.autotag import hooks
from beets.plugins import BeetsPlugin
from beets.ui.commands import PromptChoice
from beets.mediafile import TYPES
from beets.ui.commands import disambig_string
from beets import config
import musicbrainzngs
import os.path
from PIL import Image
from pyzbar.pyzbar import decode
from pyzbar.pyzbar import ZBarSymbol
from sets import Set
from collections import namedtuple


"""
requirements:
sudo apt-get install libzbar0
pip install pyzbar Pillow

TODO:
    * print => debug log
    * proper beetsplug thingy so it can be installed easier
    * release (pip, installation instructions)?
    * settings (extensions (tiff,bmp,etc), verbosity, path stuff?)
    * maybe beets.ui.get_path_formats (see beets-copyartifacts)
    * documentation
"""

PICTURE_TYPES = ("jpg", "jpeg", "png")
BARCODE_TYPES = [ZBarSymbol.EAN13,
                 ZBarSymbol.UPCA,   ZBarSymbol.UPCE,
                 ZBarSymbol.ISBN10, ZBarSymbol.ISBN13]

MatchData = namedtuple('MatchData', ['barcodes', 'album_ids'])

# dict: key = dirname, value = MatchData
_matches = {}


# utility function
def _get_files(paths, types):
    files = Set()
    for path in paths:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    # try-except because [1] and [1:] can fail
                    file_ext = os.path.splitext(filename)[1].decode('utf8')[1:]
                    full_path = os.path.join(dirpath, filename)
                    if file_ext in types:
                        files.add(full_path)
                except:
                    pass
    return files


def _get_debug_str(musicbrainzngs_release):
    release = musicbrainzngs_release
    url_prefix = "https://musicbrainz.org/release/"
    albuminfo = hooks.album_for_mbid(release['id'])
    info = []
    info.append(release['title'])
    if albuminfo:
        info.append(disambig_string(albuminfo))
    info.append(u'{}{}'.format(url_prefix, release['id']))
    return u', '.join(info)


def _process_items(items):
    release_ids = Set()

    # get paths from music tracks
    # (and directly get MB-IDs if we already have them)
    paths_original = Set()
    for i in items:
        path = os.path.dirname(i.path)
        if path not in _matches:
            paths_original.add(path)
        else:
            release_ids.update(_matches[path].album_ids)

    # append parent paths (if they dont contain more (other) media files
    # other than those we already know about)
    def _path_is_probably_ok(path, items):
        return len(_get_files([path], TYPES)) <= len(items)

    paths_updated = Set(paths_original)  # copy the original set
    for path in paths_original:
        parentdir = os.path.dirname(path)
        if _path_is_probably_ok(parentdir, items):
            paths_updated.add(parentdir)

    # get pictures from paths
    files_to_decode = _get_files(paths_updated, PICTURE_TYPES)

    # decode all pictures to find barcodes
    barcodes = Set()
    for filepath in files_to_decode:
        try:
            results = decode(Image.open(filepath), BARCODE_TYPES)
            for r in results:
                barcodes.add(r.data)
        except:
            pass

    # convert barcodes to MB-IDs
    for barcode in barcodes:
        res = musicbrainzngs.search_releases(barcode=barcode, limit=30)
        if res['release-list']:
            for release in res['release-list']:
                # print(u"{} => {}".format(barcode, _get_debug_str(release)))
                release_ids.add(release['id'])

    # add those paths and MB-IDs to our global dict
    for path in paths_original:
        _matches[path] = MatchData(barcodes, release_ids)

    return list(release_ids)


class Barcode(BeetsPlugin):
    def __init__(self):
        super(Barcode, self).__init__()
        self.config.add({
            'source_weight': 1.0,
        })
        self.register_listener('import_task_start', self.import_task_start)
        self.register_listener('before_choose_candidate', self.before_choose)

    def import_task_start(self, task, session):
        items = task.items if task.is_album else [task.item]
        _process_items(items)

    def before_choose(self, session, task):
        """
        Print a message with a list of mb-ids from scanned barcodes.
        This is useful to quickly see if the chosen release is actually
        the right one.
        """

        # task.candidates = list of AlbumMatch
        if not task.candidates:
            return None

        mb_ids = Set()
        barcodes = Set()
        for candidate in task.candidates:
            # TODO we don't have to check ALL candidates,
            # because they all use the same file paths..
            tracks = candidate.mapping
            paths = Set(map(lambda i: os.path.dirname(i.path), tracks))
            for path in paths:
                if path in _matches:
                    mb_ids.update(_matches[path].album_ids)
                    barcodes.update(_matches[path].barcodes)
        if len(mb_ids) == 0:
            return None

        print("------------------------")
        print("Found barcodes: {}".format(' '.join(barcodes)))
        print("Candidates with matching IDs:")
        for index, candidate in enumerate(task.candidates):
            album_id = candidate.info.album_id
            if album_id in mb_ids:
                print("{:2d}. {}".format(index + 1, album_id))
        print("------------------------")

        return None

    def candidates(self, items, artist, album, va_likely):
        release_ids = _process_items(items)
        releases = []
        for id in release_ids:
            albuminfo = hooks.album_for_mbid(id)
            if albuminfo:
                releases.append(albuminfo)
        return releases

    def album_distance(self, items, album_info, mapping):
        dist = hooks.Distance()

        # penalty if no barcode or id not from barcode
        paths = Set(map(lambda i: os.path.dirname(i.path), items))
        release_ids = Set()
        for path in paths:
            if path in _matches:
                release_ids.update(_matches[path].album_ids)

        # Penalty only if we actually found barcodes for this path.
        if len(release_ids) != 0:
            dist.add_expr('album_id', album_info.album_id not in release_ids)

        return dist

    def album_for_id(self, album_id):
        try:
            res = musicbrainzngs.search_releases(barcode=album_id, limit=30)
            if not res['release-list']:
                return None
        except:
            return None

        release_list = res['release-list']
        if len(release_list) > 1:
            for release in release_list:
                print(_get_debug_str(release))
            return None

        if len(release_list) == 1:
            # only return a release if we have exactly one release:
            try:
                return hooks.album_for_mbid(release_list[0]['id'])
            except:
                pass

        return None
