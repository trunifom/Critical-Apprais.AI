"""``python -m crapai``: the same as the ``crapai`` command.

The interface starts the screening in a separate process with this entry point, so that the run
goes on if the browser tab or the interface is closed (architecture decision 0006).
"""

from crapai.cli import main

if __name__ == "__main__":
    main()
