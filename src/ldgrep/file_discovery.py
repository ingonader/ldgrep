import os
import re
import sys
from pathlib import Path

from .output import print_error, progress_enabled
from .regex_utils import (
    find_excluded_directory_match,
    parse_regex_spec,
)
from .archive_handling import (
    is_allowed_extension,
    show_candidate_id_progress,
    sort_paths,
)

SUPPORTED_IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".doc",
    ".docx",
    ".odt",
    ".odp",
    ".ppt",
    ".pptx",
    ".xlsx",
    ".xls",
    ".ods",
} | SUPPORTED_IMAGE_EXTENSIONS

DEFAULT_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".odt",
    ".odp",
    ".pptx",
}

VALID_FORMATS = {extension.lstrip(".") for extension in SUPPORTED_EXTENSIONS}
IMAGE_EXTENSION_ALIASES = {"allimg", "images", "allimages"}


def _expand_image_extension_aliases(extension_spec: str | None) -> str | None:
    """Replace image pseudo-extensions with the supported image extensions.

    Args:
        extension_spec: Optional comma-separated extension specification,
            possibly prefixed with `+` or `^`.

    Returns:
        The specification with `allimg`, `images`, and `allimages` expanded
        to the supported image extensions.
    """
    if extension_spec is None:
        return None

    modifier = extension_spec[:1] if extension_spec.startswith(("+", "^")) else ""
    patterns = extension_spec[len(modifier) :].split(",")
    expanded_patterns = []
    image_extensions = [
        extension.removeprefix(".")
        for extension in sorted(SUPPORTED_IMAGE_EXTENSIONS)
    ]

    for pattern in patterns:
        if pattern.strip().casefold() in IMAGE_EXTENSION_ALIASES:
            expanded_patterns.extend(image_extensions)
        else:
            expanded_patterns.append(pattern)

    return modifier + ",".join(expanded_patterns)


def get_allowed_extensions(
    extension_spec: str | None,
) -> list[re.Pattern[str]]:
    """Compile extension patterns, including default modifiers.

    Args:
        extension_spec: Comma-separated regular expressions matched against
            file suffixes. A leading `+` adds patterns to the defaults, and a
            leading `^` removes matching extensions from the defaults. Empty
            entries select files without an extension for ordinary and `+`
            specifications. `allimg`, `images`, and `allimages` expand to all
            supported image extensions. `None` selects only the defaults.

    Returns:
        Compiled regular expressions for matching file suffixes, including the
        empty suffix when extensionless files are selected.
    """
    extension_spec = _expand_image_extension_aliases(extension_spec)
    modifier, extension_patterns = parse_regex_spec(
        extension_spec,
        re.IGNORECASE,
        empty_pattern=r"^$",
    )
    if extension_spec is not None and modifier is None:
        return extension_patterns

    allowed_extensions = []
    for extension in DEFAULT_EXTENSIONS:
        if modifier != "^" or not is_allowed_extension(
            extension, extension_patterns
        ):
            allowed_extensions.append(
                re.compile(re.escape(extension), re.IGNORECASE)
            )
    if modifier != "^":
        allowed_extensions.extend(extension_patterns)

    return allowed_extensions


def collect_files(
    inputs: list[str],
    formats: str | None = None,
    filename_pattern: re.Pattern[str] | None = None,
    sort_spec: str = "t",
    exclude_patterns: list[re.Pattern[str]] | None = None,
    excluded_paths: set[str] | None = None,
    excluded_path_patterns: dict[str, str] | None = None,
) -> list[Path]:
    """Find unique files matching extension, name, and directory filters.

    Directories are searched recursively. Nonexistent paths are reported to
    standard error and skipped.

    Args:
        inputs: File and directory paths to search.
        formats: Comma-separated extension regular expressions. A leading `+`
            adds to the default extensions, and a leading `^` removes matching
            extensions from the defaults. Empty entries select files without
            an extension. `allimg`, `images`, and `allimages` select all supported
            image extensions. `None` selects the default extensions.
        filename_pattern: Optional regular expression matched against each
            filename stem.
        sort_spec: Sort key (`a`, `c`, `t`, or `u`) and optional reverse flag
            (`r`).
        exclude_patterns: Optional expressions matched against relative
            directory paths before they are traversed.
        excluded_paths: Optional set populated with paths excluded by these
            directory patterns.
        excluded_path_patterns: Optional mapping of excluded paths to the
            pattern that matched them.

    Returns:
        Resolved matching file paths in the requested order.
    """

    allowed_extensions = get_allowed_extensions(formats)
    exclude_patterns = exclude_patterns or []

    files = set()

    for item in inputs:
        path = Path(item).expanduser()

        if not path.exists():
            print_error(f"Warning: not found: {item}")
            continue

        if path.is_file():
            relative_path = Path(os.path.relpath(path.absolute(), Path.cwd()))
            excluded_match = find_excluded_directory_match(
                relative_path.parent, exclude_patterns
            )
            if excluded_match is not None and excluded_paths is not None:
                excluded_directory, exclude_pattern = excluded_match
                excluded_path = str(excluded_directory)
                if excluded_path not in excluded_paths:
                    excluded_paths.add(excluded_path)
                    if excluded_path_patterns is not None:
                        excluded_path_patterns[excluded_path] = exclude_pattern.pattern
            if (
                excluded_match is None
                and is_allowed_extension(path.suffix, allowed_extensions)
                and (
                    filename_pattern is None
                    or filename_pattern.search(path.stem)
                )
            ):
                files.add(path.resolve())
                file_cnt = len(files)
                show_candidate_id_progress(file_cnt, "files")
            continue

        if path.is_dir():
            search_root = path.absolute()
            excluded_root = find_excluded_directory_match(path.name, exclude_patterns)
            if excluded_root is not None:
                if excluded_paths is not None:
                    excluded_directory, exclude_pattern = excluded_root
                    excluded_path = str(Path(os.path.relpath(search_root, Path.cwd())))
                    if excluded_path not in excluded_paths:
                        excluded_paths.add(excluded_path)
                        if excluded_path_patterns is not None:
                            excluded_path_patterns[excluded_path] = (
                                exclude_pattern.pattern
                            )
            else:
                for current_root, dirnames, filenames in os.walk(search_root):
                    current_path = Path(current_root)
                    relative_root = current_path.relative_to(search_root)
                    kept_dirnames = []
                    for dirname in dirnames:
                        excluded_match = find_excluded_directory_match(
                            relative_root / dirname, exclude_patterns
                        )
                        if excluded_match is None:
                            kept_dirnames.append(dirname)
                        elif excluded_paths is not None:
                            excluded_directory, exclude_pattern = excluded_match
                            excluded_path = str(
                                Path(os.path.relpath(search_root, Path.cwd()))
                                / Path(str(excluded_directory))
                            )
                            if excluded_path not in excluded_paths:
                                excluded_paths.add(excluded_path)
                                if excluded_path_patterns is not None:
                                    excluded_path_patterns[excluded_path] = (
                                        exclude_pattern.pattern
                                    )
                    dirnames[:] = kept_dirnames
                    for filename in filenames:
                        candidate = current_path / filename
                        if (
                            candidate.is_file()
                            and is_allowed_extension(
                                candidate.suffix, allowed_extensions
                            )
                            and (
                                filename_pattern is None
                                or filename_pattern.search(candidate.stem)
                            )
                        ):
                            files.add(candidate.resolve())
                            file_cnt = len(files)
                            show_candidate_id_progress(file_cnt, "files")

    if progress_enabled():
        print("\r\033[K", end="", file=sys.stderr)
    return sort_paths(files, sort_spec)
