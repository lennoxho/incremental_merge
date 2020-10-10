import argparse
import copy
import hashlib
import subprocess
import time
import json

from pymediainfo import MediaInfo
from pathlib import Path
from tqdm import tqdm, trange

CONFIG_FILENAME = "config.json"

EXTRACT_DURATION_CMD = ["ffprobe", "-hide_banner", "-select_streams", "v", "-show_entries", "frame=pkt_duration_time", "-of", "csv"]
DURATION_PREFIX = "frame,"

RACE_SAFETY_WAIT_SECONDS = 3

TEMP_SEGMENT_FILENAME = "segment_temp.mp4"
SEGMENT_FILENAME_FORMAT = "segment_%d.mp4"
UPSCALED_IMAGE_FILENAME_PATTERN = "%06d.png"

FFMPEG = "ffmpeg"
MERGE_IMAGES_CFR_ARGS = ["-y", "-hide_banner", "-loglevel", "error", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-x264-params", "keyint=15:scenecut=0", "-pix_fmt", "yuv420p", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
MERGE_IMAGES_VFR_ARGS = ["-y", "-hide_banner", "-loglevel", "error", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-x264-params", "keyint=15:scenecut=0", "-pix_fmt", "yuv420p", "-vsync", "2", "-r", "120", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2"]
MUX_ARGS = ["-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0"]
MUX_FILTER_ARGS = ["-c", "copy", "-map", "0:0", "-map", "1:1"]

CONCAT_FILENAME_FORMAT = "concat_%d.txt"
MASTER_CONCAT_FILENAME = "master_concat.txt"
CONCAT_HEADER = "ffconcat version 1.0"
CONCAT_FILE_ENTRY_PREFIX = "file "
CONCAT_DURATION_PREFIX = "duration "

FFMPEG_PROGRESS_TOKEN = "frame"

VIDEO_STREAM_INDEX = 1
AUDIO_STREAM_INDEX = 2

def log(msg):
    print(msg)

class Arguments:
    def _parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('-c', "--resume", type=str, action="store", required=False)
        parser.add_argument('-i', "--input_filename", type=str, action="store", required=False)
        parser.add_argument('-w', "--work_directory", type=str, action="store", required=False)
        parser.add_argument('-o', "--output_filename", type=str, action="store", required=False)
        parser.add_argument('-s', "--start_index", type=int, default=0, action="store", required=False)
        # 1 minutes of 30fps video, or 30 seconds of 60 fps video
        parser.add_argument('-n', "--batch_size", type=int, default=1800, action="store", required=False)
        parser.add_argument('-p', "--poll_time", type=int, default=60, action="store", required=False)

        self.__args = parser.parse_args()

        if not self.__args.resume:
            if self.__args.input_filename is None or \
               self.__args.work_directory is None or \
               self.__args.output_filename is None:
                parser.error('Input and output filenames must be specified if --resume is not set.')
        else:
            self.__args.work_directory = self.__args.resume

    def _infile_md5sum(self):
        hash_md5 = hashlib.md5()
        with open(str(self.__args.input_filename), "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)

        return hash_md5.hexdigest()

    def __init__(self):
        self._parse_args()
        self.__args.work_directory = Path(self.__args.work_directory).absolute()

        if not self.__args.resume:
            self.__args.input_filename = Path(self.__args.input_filename).absolute()
            assert self.__args.input_filename.exists(), self.__args.input_filename

            self.__args.work_directory.mkdir(exist_ok=True)

            self.__args.output_filename = Path(self.__args.output_filename).absolute()

            assert self.__args.start_index >= 0
            assert self.__args.batch_size > 0
            assert self.__args.poll_time >= 0

            self.__args.md5 = self._infile_md5sum()
        else:
            assert self.__args.work_directory.exists()

    def args(self):
        return self.__args

    def make_config(self):
        if self.__args.resume is not None:
            return None

        data = copy.deepcopy(vars(self.__args))
        del data["resume"]
        data["input_filename"] = str(data["input_filename"])
        data["work_directory"] = str(data["work_directory"])
        data["output_filename"] = str(data["output_filename"])

        return data

def verify_config(args_obj):
    def read_config(filename):
         with open(str(filename)) as hfile:
            return json.load(hfile)

    args = args_obj.args()
    current_config = args_obj.make_config()

    config_filename = args.work_directory / CONFIG_FILENAME
    config_file_exists = config_filename.exists()

    if current_config is None:
        assert config_file_exists
        prev_config = read_config(config_filename)

        args.input_filename = Path(prev_config["input_filename"])
        assert args.input_filename.exists()
        assert args.work_directory == Path(prev_config["work_directory"])
        args.output_filename = Path(prev_config["output_filename"])
        args.start_index = prev_config["start_index"]
        args.batch_size = prev_config["batch_size"]
        args.poll_time = prev_config["poll_time"]
    else:
        if not config_file_exists:
            with open(str(config_filename), 'w') as hfile:
                json.dump(current_config, hfile, indent=2)
        else:
            prev_config = read_config(config_filename)
            assert prev_config.keys() == current_config.keys(), current_config.keys()
            assert prev_config == current_config, current_config

    return args

def get_durations(input_filename):
    cmd = EXTRACT_DURATION_CMD + [str(input_filename)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True)

    durations = []
    for line in iter(proc.stdout.readline, ""):
        line = line.strip()
        if line == "": continue

        assert line.startswith(DURATION_PREFIX), line

        tokens = line.split(",")
        assert len(tokens) == 2, tokens

        durations.append(float(tokens[1]))

    proc.stdout.close()
    return_code = proc.wait()
    return durations

def verify_input_and_get_durations(input_info, input_filename):
    assert len(input_info["tracks"]) == 3
    assert input_info["tracks"][VIDEO_STREAM_INDEX]["track_type"] == 'Video'
    assert input_info["tracks"][AUDIO_STREAM_INDEX]["track_type"] == 'Audio'

    video_info = input_info["tracks"][VIDEO_STREAM_INDEX]

    frame_count = int(video_info["frame_count"])
    if video_info["frame_rate_mode"] != "CFR":
        durations = get_durations(input_filename)
        assert frame_count == len(durations), [frame_count, durations]
        return durations
    else:
        return None

def ffmpeg_track_progress(cmd, num_frames, desc):
    proc = subprocess.Popen(cmd + ["-progress", "pipe:1"], stdout=subprocess.PIPE, universal_newlines=True)

    with trange(num_frames, desc=desc) as t:
        curr_n = 0
        for line in iter(proc.stdout.readline, ""):
            line = line.strip()

            tokens = line.split('=')
            if len(tokens) == 2 and tokens[0] == FFMPEG_PROGRESS_TOKEN:
                n = int(tokens[1]) - curr_n
                assert n >= 0
                t.update(n)
                curr_n += n

    proc.stdout.close()
    return_code = proc.wait()

def generate_segment_concat_file(files, durations, concat_filename):
    assert len(files) == len(durations)

    with open(str(concat_filename), 'w') as hfile:
        hfile.write(CONCAT_HEADER + "\n")

        for i in range(len(files)):
            filename = files[i]
            hfile.write(CONCAT_FILE_ENTRY_PREFIX + "'" + filename + "'\n")

            duration = durations[i]
            hfile.write(CONCAT_DURATION_PREFIX + str(duration) + "\n")

        hfile.write(CONCAT_FILE_ENTRY_PREFIX + files[-1])

def merge_images(video_info, work_directory, begin, end, segment_filename, durations):
    filenames = [work_directory / (UPSCALED_IMAGE_FILENAME_PATTERN % i) for i in range(begin, end+1)]
    for file in filenames:
        assert file.exists(), str(file)

    temp_filename = work_directory / TEMP_SEGMENT_FILENAME
    output_args = [str(temp_filename)]

    # TODO: Progress bar using -progress pipe:1
    if video_info["frame_rate_mode"] == "CFR":
        frame_rate = video_info["frame_rate"]
        frame_rate_args = ["-framerate", str(frame_rate)]

        frame_count = end - begin + 1
        input_pattern = work_directory / UPSCALED_IMAGE_FILENAME_PATTERN
        input_args = ["-start_number", str(begin), "-i", str(input_pattern), "-vframes", str(frame_count)]

        cmd = [FFMPEG] + frame_rate_args + input_args + MERGE_IMAGES_CFR_ARGS + output_args
        ffmpeg_track_progress(cmd, frame_count, "Writing \"%s\"" % segment_filename.name)
    else:
        concat_filename = work_directory / (CONCAT_FILENAME_FORMAT % i)
        generate_segment_concat_file(filenames, durations, concat_filename)

        input_args = ["-i", str(concat_filename)]

        cmd = [FFMPEG] + input_args + MERGE_IMAGES_VFR_ARGS + output_args
        ffmpeg_track_progress(cmd, len(durations), "Writing \"%s\"" % segment_filename.name)

    temp_filename.rename(segment_filename)

    for file in tqdm(filenames, desc="Deleting src... eidx=" + str(end)):
        file.unlink()

def merge_images_loop(video_info, args, durations):
    def wait(end_filename, t):
        while not end_filename.exists():
            t.set_description("Waiting for \"%s\"" % end_filename.name)
            time.sleep(args.poll_time)

        # The file might be in the middle of being written to
        time.sleep(RACE_SAFETY_WAIT_SECONDS)

    frame_count = int(video_info["frame_count"])
    num_segments = frame_count // args.batch_size

    segments = []
    with trange(num_segments) as t:
        for i in t:
            t.set_description("Progress")
            segment_filename = args.work_directory / (SEGMENT_FILENAME_FORMAT % i)

            if not segment_filename.exists():
                begin = args.start_index + i * args.batch_size
                end = begin + args.batch_size - 1
                if i + 1 == num_segments:
                    end = args.start_index + frame_count - 1

                segment_durations = durations[begin:end+1] if durations is not None else None

                end_filename = args.work_directory / (UPSCALED_IMAGE_FILENAME_PATTERN % end)
                wait(end_filename, t)
                merge_images(video_info, args.work_directory, begin, end, segment_filename, segment_durations)

            # To force tqdm to update. Turns out tqdm is polling based :/
            time.sleep(0.1)
            segments.append(segment_filename)

    # Sanity check
    time.sleep(RACE_SAFETY_WAIT_SECONDS)
    past_the_end = args.work_directory / (UPSCALED_IMAGE_FILENAME_PATTERN % (args.start_index + frame_count))
    assert not past_the_end.exists()

    return segments

def merge_segments(args, video_info, segments):
    concat_filename = args.work_directory / MASTER_CONCAT_FILENAME
    with open(str(concat_filename), 'w') as hfile:
        hfile.write(CONCAT_HEADER + "\n")

        for segment in segments:
            hfile.write(CONCAT_FILE_ENTRY_PREFIX + "'" + str(segment) + "'\n")

    input_args = ["-i", str(concat_filename), "-i", str(args.input_filename)]
    output_args = [str(args.output_filename)]

    cmd = [FFMPEG] + MUX_ARGS + input_args + MUX_FILTER_ARGS + output_args
    ffmpeg_track_progress(cmd, int(video_info["frame_count"]), "Progress")

if __name__ == "__main__":
    args_obj = Arguments()

    log("Verifying configuration...")
    args = verify_config(args_obj)

    log("Extracing input video metadata...")
    input_info = MediaInfo.parse(str(args.input_filename)).to_data()
    durations = verify_input_and_get_durations(input_info, args.input_filename)

    video_info = input_info["tracks"][VIDEO_STREAM_INDEX]

    log("\nCreating segments...")
    segments = merge_images_loop(video_info, args, durations)

    log("Merging segments into final video: \"%s\"" % str(args.output_filename))
    merge_segments(args, video_info, segments)