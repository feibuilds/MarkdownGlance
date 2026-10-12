from .preview.adapter.commands import *
from .preview.adapter.container import container
from .preview.adapter.events import *


def plugin_loaded():
    container.build()
    # Say so once at load, with the fix, rather than on the first render. Only
    # the lookup: the first start after Sublime Text itself is upgraded is when
    # Package Control installs the libraries for the new Python, and it asks
    # for the restart then. A command still loads them before it runs.
    libraries_missing(load=False)


def plugin_unloaded():
    container.unload()
