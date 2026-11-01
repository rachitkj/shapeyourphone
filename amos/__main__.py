import sys

if sys.version_info < (3, 9):
    sys.exit("amos needs Python 3.9 or newer (you have %s)." % sys.version.split()[0])

from .cli import main  # noqa: E402

sys.exit(main())
