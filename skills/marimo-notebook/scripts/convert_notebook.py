#!/usr/bin/env python3
"""Convert Jupyter notebooks to marimo format."""

import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def _derive_output_path(input_path: str) -> str:
    """Derive a .py output path from a local file path or GitHub URL."""
    if input_path.startswith(("http://", "https://")):
        # Path() on a URL collapses the "//" after the scheme, so pull the
        # filename out of the URL's path component instead of the raw string.
        name = Path(urlparse(input_path).path).name
        if not name:
            raise ValueError(f"Could not derive a filename from URL: {input_path}")
        return str(Path(name).with_suffix(".py"))
    return str(Path(input_path).with_suffix(".py"))


def convert_jupyter_to_marimo(input_path: str, output_path: str | None = None) -> str:
    """Convert a Jupyter notebook to marimo format.

    Args:
        input_path: Path to .ipynb file (local or GitHub URL)
        output_path: Optional output path. If None, derives from input.

    Returns:
        Path to the created marimo notebook.
    """
    if output_path is None:
        output_path = _derive_output_path(input_path)

    if Path(output_path).exists():
        raise FileExistsError(
            f"Output path already exists: {output_path} "
            "(pass an explicit output path to overwrite it intentionally)"
        )

    cmd = ["marimo", "convert", input_path, "-o", output_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise RuntimeError(
            "Conversion failed: the `marimo` command is not installed "
            "(pip install marimo)"
        ) from e

    if result.returncode != 0:
        raise RuntimeError(f"Conversion failed: {result.stderr}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: convert_notebook.py <input.ipynb> [output.py]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        result = convert_jupyter_to_marimo(input_file, output_file)
        print(f"Converted to: {result}")
    except (RuntimeError, FileExistsError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
