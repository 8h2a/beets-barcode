"""Adds barcode support to the autotagger.
Requires pyzbar, PIL/Pillow, (and libzbar0).

This plugin allows entering barcode as IDs to find the exact release
and it also searches all image files for barcodes to help in selecting
the correct release.
If it finds a barcode, it gets the release-id from musicbrainz and
penalizes releases which don't correspond to the found barcode(s).

requirements:
sudo apt-get install libzbar0
pip install pyzbar Pillow

TODO:
    * documentation
    * proper beetsplug thingy so it can be installed easier
    * release (pip, installation instructions)?

TODO LATER:
    * if no barcode found:
        check if there are different releases in that release group.
        if yes, tell the user to consider providing a barcode/ID/catalog#
    * search on discogs (if not found on mb)
      are we allowed to call get_albums() from the discogs plugin?
    * print => debug log?
    * settings (extensions (tiff,bmp,etc), verbosity, path stuff?)
    * bad pictures (low resolution, heavy jpeg compression) dont yield barcodes

"""
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
from collections import namedtuple

PICTURE_TYPES = ("jpg", "jpeg", "png")
BARCODE_TYPES = [ZBarSymbol.EAN13,
                 ZBarSymbol.UPCA,   ZBarSymbol.UPCE,
                 ZBarSymbol.ISBN10, ZBarSymbol.ISBN13]

# Note: "barcodes" and "album_ids" are sets
MatchData = namedtuple('MatchData', ['barcodes', 'album_ids'])
_matches = {}  # dict: key = dirname, value = MatchData


# utility function
def _get_files(paths, types):
    """Gets all files (file names) with a specific type (file extension(s))
    in the provided path(s) and all their sub-directories.
    """
    files = set()
    for path in paths:
        for dirpath, dirnames, filenames in os.walk(path):
            for filename in filenames:
                try:
                    # try-except because [1] and [1:] can fail
                    file_ext = os.path.splitext(filename)[1].decode('utf8')[1:]
                    if file_ext in types:
                        full_path = os.path.join(dirpath, filename)
                        files.add(full_path)
                except:
                    pass
    return files


def _get_debug_str(albuminfo):
    """Gets a string with more information (disambig_string) from a AlbumInfo.
    """
    info = []
    info.append(albuminfo.album)
    info.append(disambig_string(albuminfo))
    info.append(albuminfo.data_source)
    info.append(albuminfo.album_id)
    return u', '.join(info)


def _barcodes_to_albuminfos(barcodes):
    """Converts a list of barcodes to a list of AlbumInfo objects
    """
    releases = []
    for barcode in barcodes:
        res = musicbrainzngs.search_releases(barcode=barcode, limit=30)
        if res['release-list']:
            for release in res['release-list']:
                try:
                    releases.append(hooks.album_for_mbid(release['id']))
                except:
                    pass
        # TODO else discogs?
    return releases


def _process_items(items):
    """Find barcodes from image files from the provided list of items.
    Used in import_task_start to populate the global dictionary "_matches"
    with path/barcode/release-id combinations,
    which are then later used during the autotagging candidate search.
    The function will not re-scan already processed paths, instead it will
    simply look up the values from "_matches".
    """
    release_ids = set()

    # get paths from music tracks
    # (and directly get MB-IDs if we already have them)
    paths_original = set()
    for item in items:
        path = os.path.dirname(item.path)
        if path not in _matches:
            paths_original.add(path)
        else:
            release_ids.update(_matches[path].album_ids)

    # append parent paths if they dont contain more (other) media files
    # (other than those we already know about)
    def _path_is_probably_ok(path, items):
        return len(_get_files([path], TYPES)) <= len(items)

    paths = set(paths_original)  # copy the original set
    parentpaths = set(map(os.path.dirname, paths_original))
    for parentdir in parentpaths:
        if _path_is_probably_ok(parentdir, items):
            paths.add(parentdir)

    # get pictures from paths
    files_to_decode = _get_files(paths, PICTURE_TYPES)

    # decode all pictures to find barcodes
    barcodes = set()
    for filepath in files_to_decode:
        try:
            results = decode(Image.open(filepath), BARCODE_TYPES)
            for r in results:
                barcodes.add(r.data)
        except:
            pass

    # convert barcodes to MB-IDs and add them to our set
    albuminfos = _barcodes_to_albuminfos(barcodes)
    release_ids.update(set(map(lambda info: info.album_id, albuminfos)))

    # add those paths and MB-IDs to our global dict:
    # Note we're using "paths_original" instead of "paths", which would also
    # contain their parent-paths, to match them to the item paths later.
    for path in paths_original:
        _matches[path] = MatchData(barcodes, release_ids)

    return list(release_ids)


class Barcode(BeetsPlugin):
    def __init__(self):
        super(Barcode, self).__init__()
        self.config.add({
            'source_weight': 0.9,
        })
        self.register_listener('import_task_start', self.import_task_start)
        self.register_listener('before_choose_candidate', self.before_choose)

    def import_task_start(self, task, session):
        items = task.items if task.is_album else [task.item]
        _process_items(items)

    def before_choose(self, session, task):
        """Prints a helpful message to tell which candidate corresponds to the
        scanned barcodes.
        This is useful to quickly see if the chosen release is the correct one.
        """

        # Note: task.candidates = list of AlbumMatch
        if not task.candidates:
            return None

        mb_ids = set()
        barcodes = set()
        for candidate in task.candidates:
            # TODO we don't have to check ALL candidates,
            # because they all use the same file paths..
            tracks = candidate.mapping
            paths = set(map(lambda i: os.path.dirname(i.path), tracks))
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
            if candidate.info.album_id in mb_ids:
                print("{:2d}. {} {}".format(
                    index + 1,
                    candidate.info.album_id,
                    disambig_string(candidate.info)
                ))
        print("------------------------")

        return None

    def candidates(self, items, artist, album, va_likely):
        release_ids = _process_items(items)
        releases = []
        for id in release_ids:
            try:  # album_for_mbid may raise a MusicBrainzAPIError
                albuminfo = hooks.album_for_mbid(id)
                if albuminfo:
                    releases.append(albuminfo)
            except:
                pass
        return releases

    def album_distance(self, items, album_info, mapping):
        dist = hooks.Distance()

        # Add a penalty if these items have a barcode, but the album_id
        # is does not correspond to the barcode(s).
        paths = set(map(lambda item: os.path.dirname(item.path), items))
        release_ids = set()
        for path in paths:
            if path in _matches:
                release_ids.update(_matches[path].album_ids)

        # Penalty only if we actually found barcodes for this path,
        # to avoid penalizing all relases if we haven't found any barcodes.
        if len(release_ids) != 0:
            dist.add_expr('album_id', album_info.album_id not in release_ids)

        return dist

    def album_for_id(self, album_id):
        """Looks up the barcode in the musicbrainz database and returns the
        matching album (if the barcode corresponds to exactly one release).
        """
        albuminfos = _barcodes_to_albuminfos([album_id])

        if len(albuminfos) == 0:
            return None

        if len(albuminfos) > 1:
            print("Found multiple matching releases:")
            for albuminfo in albuminfos:
                print(_get_debug_str(albuminfo))
            return None

        # return an AlbumInfo if we found exactly one release
        try:  # album_for_mbid may raise a MusicBrainzAPIError
            return albuminfos[0]
        except:
            pass

        return None
