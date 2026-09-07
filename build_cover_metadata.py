#!/usr/bin/env python3
"""
build_cover_metadata.py <cover_image> <output_metadata_file>

Builds an ffmpeg "ffmetadata" file containing a single
METADATA_BLOCK_PICTURE tag, following the Xiph.org / FLAC picture
metadata block spec:

    https://xiph.org/flac/format.html#metadata_block_picture
    https://wiki.xiph.org/VorbisComment#Cover_art

This is the only cover-art embedding method Ogg Vorbis and Opus
players are expected to recognise. ffmpeg's `-disposition:v
attached_pic` shortcut (used for FLAC/MP3) does NOT produce this tag
for Ogg-family containers, so the value has to be built by hand and
fed back into ffmpeg via `-i metadata.txt -map_metadata 1`, which
avoids passing a large base64 blob as a shell/command-line argument.

Exits with a non-zero status and prints nothing to the metadata file
on any failure, so the caller can detect and handle it.
"""

import base64
import os
import struct
import subprocess
import sys

PICTURE_TYPE_FRONT_COVER = 3


def guess_mime_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        return "image/png"
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    return "image/jpeg"


def probe_dimensions(path):
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                path,
            ],
            stderr=subprocess.DEVNULL,
        ).decode("ascii", errors="ignore").strip()
        width_str, height_str = out.split(",")[:2]
        return int(width_str), int(height_str)
    except Exception:
        return 0, 0


def build_picture_block(image_path):
    mime = guess_mime_type(image_path)
    width, height = probe_dimensions(image_path)
    depth = 24
    colors = 0
    description = b""

    with open(image_path, "rb") as f:
        image_data = f.read()

    mime_bytes = mime.encode("ascii")

    block = b"".join([
        struct.pack(">I", PICTURE_TYPE_FRONT_COVER),
        struct.pack(">I", len(mime_bytes)),
        mime_bytes,
        struct.pack(">I", len(description)),
        description,
        struct.pack(">I", width),
        struct.pack(">I", height),
        struct.pack(">I", depth),
        struct.pack(">I", colors),
        struct.pack(">I", len(image_data)),
        image_data,
    ])

    return base64.b64encode(block).decode("ascii")


def main():
    if len(sys.argv) != 3:
        sys.stderr.write(
            "usage: build_cover_metadata.py <cover_image> "
            "<output_metadata_file>\n"
        )
        return 1

    image_path, output_path = sys.argv[1], sys.argv[2]

    try:
        b64_block = build_picture_block(image_path)
    except Exception as exc:
        sys.stderr.write(f"Failed to build picture block: {exc}\n")
        return 1

    try:
        with open(output_path, "w", encoding="ascii", newline="\n") as f:
            f.write(";FFMETADATA1\n")
            f.write("METADATA_BLOCK_PICTURE=" + b64_block + "\n")
    except Exception as exc:
        sys.stderr.write(f"Failed to write metadata file: {exc}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
