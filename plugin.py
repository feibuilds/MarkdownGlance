from .preview.adapter.commands import *
from .preview.adapter.container import container
from .preview.adapter.events import *


def plugin_loaded():
    container.build()
    # Say so once at load, with the fix, rather than on the first render.
    libraries_missing()


def plugin_unloaded():
    container.unload()
