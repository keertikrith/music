import os
import json
import numpy as np
from tqdm import tqdm
from yt_dlp import YoutubeDL
from moviepy.editor import AudioFileClip, concatenate_audioclips
from moviepy.audio.AudioClip import AudioClip


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
    parts = list(map(int, ts.split(":")))
    if len(parts) == 2:          # MM:SS
        m, s = parts
        return m * 60 + s
    elif len(parts) == 3:        # HH:MM:SS
        h, m, s = parts
        return h * 3600 + m * 60 + s
    else:
        raise ValueError(f"Invalid timestamp: {ts}")


# --------- SILENCE CREATOR ----------
def generate_silence(duration, fps=44100):
    return AudioClip(lambda t: np.zeros_like(t), duration=duration, fps=fps)


# --------- DOWNLOAD HANDLER ----------
def download_audio(url, name):
    output_mp3 = os.path.join(SOURCE_DIR, f"{name}.mp3")

    if os.path.exists(output_mp3):
        print(f"✔ Skipping download (exists): {output_mp3}")
        return output_mp3

    print(f"\n⬇ Downloading YouTube audio for: {name}")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(SOURCE_DIR, f"{name}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "0",
        }]
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    print(f"✔ Saved: {output_mp3}")
    return output_mp3


# --------- MAIN PROCESSOR ----------
def trim_and_merge_from_json(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)

    songs = data["songs"]
    output_name = data.get("output_file", "merged_output.mp3")
    output_file = os.path.join(OUTPUT_DIR, output_name)

    final_clips = []

    print("\n🎶 Starting Processing...\n")

    # LOOP WITH PROGRESS BAR
    for info in tqdm(songs, desc="Processing Songs", unit="song"):

        name = info["name"]
        url_or_path = info["url"]

        # ----- GET AUDIO -----
        if url_or_path.startswith("http"):
            audio_path = download_audio(url_or_path, name)
        else:
            audio_path = os.path.join(SOURCE_DIR, f"{name}.mp3")
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"Local audio not found: {audio_path}")

        # ----- TIMESTAMPS -----
        start_sec = parse_timestamp(info["start"])
        end_sec = parse_timestamp(info["end"])
        gap_after = info.get("gap_after", 0)

        print(f"\n🎵 Trimming {name}: {info['start']} → {info['end']}")

        # ----- TRIM AUDIO -----
        audio_clip = AudioFileClip(audio_path).subclip(start_sec, end_sec)

        trimmed_path = os.path.join(TRIM_DIR, f"{name}_trimmed.mp3")

        # pseudo progress bar for trimming
        for _ in tqdm(range(50), desc=f"Trimming {name}", unit="%", ncols=80, leave=False):
            pass

        audio_clip.write_audiofile(trimmed_path, verbose=False, logger=None)

        final_clips.append(audio_clip)

        # ----- GAP -----
        if gap_after > 0:
            final_clips.append(generate_silence(gap_after))

    # ----- MERGE AUDIO -----
    print("\n🔗 Merging all clips...")

    # merge progress bar
    for _ in tqdm(range(100), desc="Merging Audio", unit="%", ncols=80):
        pass

    final_audio = concatenate_audioclips(final_clips)

    final_audio.write_audiofile(output_file)
    print(f"\n🎉 DONE! Output saved at:\n{output_file}")


# --------- MAIN ---------
if __name__ == "__main__":
    trim_and_merge_from_json("last_performance.json")
