"""A file-based cache system for reading/writing files."""

from pathlib import Path

from spoolman.env import get_cache_dir

# How many times this process has rewritten each cache file, by name. A reader that caches what
# it parsed from a file keys on this as well as the file's stat: two writes of the same size
# within the timestamp granularity of the filesystem (a second on some) leave the stat unchanged.
_generations: dict[str, int] = {}


def generation(name: str) -> int:
    """Return how many times this process has rewritten the named cache file."""
    return _generations.get(name, 0)


def get_file(name: str) -> Path:
    """Get the path to a file in the cache dir."""
    return get_cache_dir() / name


def update_file(name: str, data: bytes) -> None:
    """Update a file if it differs from the given data."""
    path = get_file(name)
    if path.exists() and path.read_bytes() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _generations[name] = generation(name) + 1


def get_file_contents(name: str) -> bytes:
    """Get the contents of a file."""
    path = get_file(name)
    return path.read_bytes()
