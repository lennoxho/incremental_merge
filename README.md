# incremental_merge
Daemon script to incrementally merge images into video.

Initially written to provde basic pause/resume capability to the [Topaz Video Enhance AI software](https://topazlabs.com/video-enhance-ai/).\
Also increases stability by not relying on VEAI's mp4 output mode (which crashes intermittently), opting instead to manually stitch together produced frames.

Requirements
============
1. Python 3.4+
    * pymediainfo `pip install pymediainfo`
    * tqdm `pip install tqdm`
    * PIL `pip install pillow`
2. ffmpeg+ffprobe
    * Make sure both executables are added to PATH

Basic Usage
===========
incremental_merge.py is meant to be run as a background task while VEAI is running.

The two applications can be launced independently of each other. The order does not matter.\
However, it is recommended to have incremental_merge.py on standby to merge and delete processed images to keep disk space usage low.

First run
---------
```
python incremental_merge.py -i <input>.mp4 -w <work directory> -o <output>.mp4
```
Start the VEAI GUI, select video and AI model. Change output directory to \<work directory\>. \
Make sure output mode is set to "PNG". Start processing.

Pause/stop
----------
Perform a keyboard interrupt (ctrl-C).\
Hit the stop button on the VEA GUI.

Resume
------
```
python incremental_merge.py -c <work directory>
```
Start the VEAI GUI, select same options as before.\
**Change start frame index to where it left off** (otherwise you'll be wasting time). Start processing.

Command Line Reference
======================
```
usage: incremental_merge.py [-h] [-c RESUME] [-i INPUT_FILENAME]
                            [-w WORK_DIRECTORY] [-o OUTPUT_FILENAME]
                            [-s START_INDEX] [-n BATCH_SIZE] [-p POLL_TIME]
```

Notes and caveats
=================
1. Only .mp4 inputs and .png intermediate files are supported. Other formats should work (small modifications required), but is untested.
2. I'm not an ffmpeg expert, just trying my best with what limited knowledge I have with ffmpeg :/.
3. Disk space usage can be brutal. Expect up to 5GB used throughout the processing process (assuming default batch size and 1080p output frames).

extract.py
==========
Simple script to extract the [n, n+x]th frames from a given video
```
python extract.py -i <input>.mp4 -o <image>.png -s <index>
```
