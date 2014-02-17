import sys

################################
## Add Submodules to sys.path ##
################################
import os
this_file = os.path.abspath(__file__)
this_file = os.path.realpath( this_file )
ilastik_package_dir = os.path.dirname(this_file)
ilastik_repo_dir = os.path.dirname(ilastik_package_dir)
submodule_dir = os.path.join( ilastik_repo_dir, 'submodules' )

# Add all submodules to the PYTHONPATH
import expose_submodules
expose_submodules.expose_submodules(submodule_dir)

##################
## Version info ##
##################

def _format_version(t):
    """converts a tuple to a string"""
    return '.'.join(str(i) for i in t)

__version_info__ = (1, 0, 0)
__version__ = _format_version(__version_info__)

core_developers = [ "Stuart Berg", 
                    "Fred Hamprecht", 
                    "Bernhard Kausler", 
                    "Anna Kreshuk", 
                    "Ullrich Koethe", 
                    "Thorben Kroeger", 
                    "Martin Schiegg", 
                    "Christoph Sommer", 
                    "Christoph Straehle" ]

developers = [ "Markus Doering", 
               "Kemal Eren", 
               "Burcin Erocal", 
               "Luca Fiaschi", 
               "Carsten Haubold", 
               "Ben Heuer", 
               "Philipp Hanslovsky", 
               "Kai Karius", 
               "Jens Kleesiek", 
               "Markus Nullmeier", 
               "Oliver Petra", 
               "Buote Xu", 
               "Chong Zhang" ]

def convertVersion(vstring):
    if not isinstance(vstring, str):
        raise Exception('tried to convert non-string version: {}'.format(vstring))
    return tuple(int(i) for i in vstring.split('.'))


def isVersionCompatible(version):
    """Return True if the current project file format is
    backwards-compatible with the format used in this version of
    ilastik.

    """
    # Currently we aren't forwards or backwards compatible with any
    # other versions.

    # for now, also allow old-style floats as version numbers
    if isinstance(version, float):
        return float(_format_version(__version_info__[0:2])) == version
    return convertVersion(version) == __version_info__

#######################
## Dependency checks ##
#######################

def _do_check(fnd, rqd, msg):
    if fnd < rqd:
        fstr = _format_version(fnd)
        rstr = _format_version(rqd)
        raise Exception(msg.format(fstr, rstr))

def _check_depends():
    import h5py

    _do_check(h5py.version.version_tuple,
              (2, 1, 0),
              "h5py version {0} too old; versions of h5py before {1} are not threadsafe.")

_check_depends()