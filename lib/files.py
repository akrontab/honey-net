import shutil


def copy_tree(src, dst, exclude_names=None):
    """Recursively copy src → dst, skipping files whose names are in exclude_names."""
    exclude = set(exclude_names or [])

    def _ignore(_, names):
        return {n for n in names if n in exclude}

    shutil.copytree(src, dst, ignore=_ignore)
