import os
import json
import subprocess
import concurrent.futures
from yt_dlp import YoutubeDL

# --------- FOLDER PATHS ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(BASE_DIR, "source-files")
TRIM_DIR = os.path.join(BASE_DIR, "trimmed-files")
OUTPUT_DIR = os.path.join(BASE_DIR, "output-files")

os.makedirs(SOURCE_DIR, exist_ok=True)
os.makedirs(TRIM_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


# --------- TIMESTAMP PARSER ----------
def parse_timestamp(ts):
    """
    Parse timestamp in formats:
    MM:SS, MM:SS.ms, HH:MM:SS, HH:MM:SS.ms
    Returns total seconds as float.
    """
    parts = ts.split(":")
    
    # Handle the last part which may have milliseconds
    last_part = parts[-1]
    if "." in last_part:
        sec_str, ms_str = last_part.split(".")
        seconds = float(sec_str)
        milliseconds = float(ms_str) / 1000  # convert ms to seconds
        last_part_value = seconds + milliseconds
    else:
        last_part_value = float(last_part)
    
    if len(parts) == 2:
        m = int(parts[0])
        return m * 60 + last_part_value
    elif len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        return h * 3600 + m * 60 + last_part_value
    else:
        raise ValueError(f"Invalid timestamp: {ts}")


# --------- FFMPEG RUNNER ----------
def run_ffmpeg(cmd):
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in process.stdout:
        print(line.strip())
    process.wait()


# --------- DOWNLOAD HANDLER ----------
def download_audio(info):
    name = info["name"]
    url = info["url"]
    mp3_path = os.path.join(SOURCE_DIR, f"{name}.mp3")

    if os.path.exists(mp3_path):
        return mp3_path

    print(f"\n⬇ Downloading: {name}")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(SOURCE_DIR, f"{name}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "0",
            }
        ],
        "extractor_args": {"youtube:player_client": "default"}
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return mp3_path


# --------- SILENCE CREATOR ----------
def generate_silence(duration, out_path):
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration),
        out_path,
    ]
    run_ffmpeg(cmd)


# --------- TRIM + FADES + PER-CLIP NORMALIZATION ----------
def trim_audio(info):
    name = info["name"]
    input_path = os.path.join(SOURCE_DIR, f"{name}.mp3")
    out_path = os.path.join(TRIM_DIR, f"{name}_trimmed.mp3")

    start_sec = parse_timestamp(info["start"])
    end_sec = parse_timestamp(info["end"])
    duration = end_sec - start_sec

    fade_in = float(info.get("fade_in", 0))
    fade_out = float(info.get("fade_out", 0))

    print(f"\n🎵 Processing {name}: {info['start']} → {info['end']}")

    # ---- Fades ----
    af_filters = []

    if fade_in > 0:
        af_filters.append(f"afade=t=in:ss=0:d={fade_in}")

    if fade_out > 0:
        fade_out_start = duration - fade_out
        fade_out_start = max(fade_out_start, 0)
        af_filters.append(f"afade=t=out:st={fade_out_start}:d={fade_out}")

    # ---- Per-clip Loudness Normalization (LUFS) ----
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=7"
    af_filters.append(loudnorm)

    filter_chain = ",".join(af_filters)

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", input_path,
        "-t", str(duration),
        "-af", filter_chain,
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        out_path,
    ]

    run_ffmpeg(cmd)
    return out_path


# --------- MAIN PIPELINE ----------
def trim_and_merge_from_json(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)

    songs = data["songs"]
    output_name = data.get("output_file", "merged_output.mp3")
    final_raw_path = os.path.join(OUTPUT_DIR, "temp_un_normalized_mix.mp3")
    final_output_path = os.path.join(OUTPUT_DIR, output_name)

    print("\n============================")
    print("  PARALLEL DOWNLOADING")
    print("============================\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as exec:
        list(exec.map(download_audio, songs))

    print("\n============================")
    print("  TRIMMING + EFFECTS + PER-CLIP NORMALIZATION")
    print("============================\n")

    trimmed_files = []

    for info in songs:
        trimmed = trim_audio(info)
        trimmed_files.append(trimmed)

        gap = info.get("gap_after", 0)
        if gap > 0:
            silence_path = os.path.join(TRIM_DIR, f"{info['name']}_silence.mp3")
            generate_silence(gap, silence_path)
            trimmed_files.append(silence_path)

    merge_list_path = os.path.join(TRIM_DIR, "merge_list.txt")
    with open(merge_list_path, "w") as f:
        for file in trimmed_files:
            f.write(f"file '{file}'\n")

    print("\n============================")
    print("  MERGING (PRE-NORMALIZED)")
    print("============================\n")

    merge_cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", merge_list_path,
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        final_raw_path
    ]
    run_ffmpeg(merge_cmd)

    print("\n============================")
    print("  FINAL MIX NORMALIZATION (LUFS)")
    print("============================\n")

    final_norm_cmd = [
        "ffmpeg", "-y",
        "-i", final_raw_path,
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=7",
        "-acodec", "libmp3lame",
        "-b:a", "192k",
        final_output_path
    ]
    run_ffmpeg(final_norm_cmd)

    print("\n🎉 MIX COMPLETED SUCCESSFULLY!")
    print(f"👉 Final file: {final_output_path}")


# --------- ENTRY POINT ----------
if __name__ == "__main__":
    trim_and_merge_from_json("chandana_n_yashwant.json")
