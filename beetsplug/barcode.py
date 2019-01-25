"""
TODO:
    * settings? (extensions (tiff,bmp,etc), verbosity, path stuff?)
    * bad pictures (low resolution, heavy jpeg compression) dont yield barcodes
"""
from beets import ui
from beets.autotag import hooks
from beets.plugins import BeetsPlugin
from beets.ui.commands import PromptChoice
from beets.mediafile import TYPES
from beets.ui.commands import disambig_string
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
                    if file_ext.lower() in types:
                        full_path = os.path.join(dirpath, filename)
                        files.add(full_path)
                except:
                    pass
    return files


def _get_debug_str(albuminfo):
    """Gets a string with more information (disambig_string) from an
    AlbumInfo object.
    """
    info = []
    if albuminfo.album_id:
        info.append(albuminfo.album_id)
    if albuminfo.album:
        info.append(albuminfo.album)
    if albuminfo.catalognum:
        info.append(albuminfo.catalognum)
    info.append(disambig_string(albuminfo))
    return u', '.join(info)


def _barcodes_to_albuminfos(barcodes):
    """Converts a list of barcodes to a list of AlbumInfo objects
    """
    releases = []
    for barcode in barcodes:
        res = musicbrainzngs.search_releases(
            barcode=barcode,
            catno=barcode,
            limit=30)
        if res['release-list']:
            for release in res['release-list']:
                try:
                    releases.append(hooks.album_for_mbid(release['id']))
                except:
                    pass
    return releases

def _files_to_barcodes(filenames):
    """Decodes a list of filenames and returns a set of barcodes."""
    # decode all pictures to find barcodes
    barcodes = set()
    for filepath in filenames:
        try:
            results = decode(Image.open(filepath), BARCODE_TYPES)
            for r in results:
                barcodes.add(r.data)
        except:
            pass
    return barcodes

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
    barcodes = _files_to_barcodes(files_to_decode)

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

        ids = set()
        barcodes = set()
        for candidate in task.candidates:
            # TODO we don't have to check ALL candidates,
            # because they all use the same file paths..
            tracks = candidate.mapping
            paths = set(map(lambda i: os.path.dirname(i.path), tracks))
            for path in paths:
                if path in _matches:
                    ids.update(_matches[path].album_ids)
                    barcodes.update(_matches[path].barcodes)
        if len(barcodes) == 0:
            return None

        #print("------------------------")
        if len(ids) == 0:
            print("{}: {}".format(
                ui.colorize('text_warning', 
                    "Found barcode(s) but no matching releases"),
                ' '.join(barcodes)))
        else:
            print("{}: {}".format(
                ui.colorize('text_success', "Found barcode(s)"),
                ' '.join(barcodes)))
        #    print("Candidates with matching IDs:")
        #    for index, candidate in enumerate(task.candidates):
        #        info = candidate.info
        #        if info.album_id in ids:
        #            print(u"{:2d}. {}".format(index + 1, _get_debug_str(info)))
        #print("------------------------")

        return None

    def candidates(self, items, artist, album, va_likely):
        # TODO we already have album infos in _process_items.
        # we should cache and reuse them.
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
        # does not correspond to the barcode(s).
        paths = set(map(lambda item: os.path.dirname(item.path), items))
        release_ids = set()
        for path in paths:
            if path in _matches:
                release_ids.update(_matches[path].album_ids)

        # Penalty only if we actually found barcodes for this path,
        # to avoid penalizing all relases if we haven't found any barcodes.
        if len(release_ids) != 0:
            dist.add_expr('barcode', album_info.album_id not in release_ids)
            if album_info.album_id in release_ids:
                album_info.data_source+='+' + ui.colorize('text_success', 'barcode')

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
