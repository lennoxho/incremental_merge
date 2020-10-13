# Simple script to extract a range of frames from video

import argparse
import subprocess

from pathlib import Path

FFMPEG = "ffmpeg"
SELECT_FORMAT = "select=gte(n\,%d)"
VFRAMES_ARGS = ["-vframes"]
EXTRACT_ARGS = ["-y", "-hide_banner", "-loglevel", "error", "-vf"]

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-i', "--input_filename", type=str, action="store", required=True)
    parser.add_argument('-o', "--output_filename", type=str, action="store", required=True)
    parser.add_argument('-s', "--start_index", type=int, default=0, action="store", required=False)
    parser.add_argument('-n', "--num_frames", type=int, default=1, action="store", required=False)
    args = parser.parse_args()

    args.input_filename = Path(args.input_filename).absolute()
    assert args.input_filename.exists()
    args.output_filename = Path(args.output_filename).absolute()

    assert args.input_filename != args.output_filename
    assert args.start_index >= 0
    assert args.num_frames >= 1

    return args

if __name__ == "__main__":
    args = parse_args()

    input_args = ["-i", str(args.input_filename)]
    output_args = [str(args.output_filename)]

    select_args = [SELECT_FORMAT % args.start_index]
    vframes_args = VFRAMES_ARGS + [str(args.num_frames)]

    cmd = [FFMPEG] + input_args + EXTRACT_ARGS + select_args + vframes_args + output_args
    subprocess.check_call(cmd)