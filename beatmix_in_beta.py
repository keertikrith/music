import os
import json
import subprocess
import concurrent.futures

from yt_dlp import YoutubeDL
import librosa

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
    print("\n▶ ffmpeg:", " ".join(str(c) for c in cmd))
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
        print(f"✔ Already downloaded: {name}")
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
        "extractor_args": {"youtube:player_client": "default"},
    }

    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    return mp3_path


# --------- PER-CLIP BPM DETECTION ----------
def detect_bpm(audio_path):
    print(f"\n🧠 Detecting BPM for {os.path.basename(audio_path)} ...")
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
    tempo = float(tempo)
    print(f"   → Estimated BPM: {tempo:.2f}")
    return tempo if tempo > 0 else 120.0  # fallback if weird


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

    print(f"\n🎵 Processing {name}: {info['start']} → {info['end']} (duration {duration}s)")

    af_filters = []

    # fade-in
    if fade_in > 0:
        af_filters.append(f"afade=t=in:ss=0:d={fade_in}")

    # fade-out
    if fade_out > 0:
        fade_out_start = duration - fade_out
        fade_out_start = max(fade_out_start, 0)
        af_filters.append(f"afade=t=out:st={fade_out_start}:d={fade_out}")

    # per-clip loudness normalization
    loudnorm = "loudnorm=I=-14:TP=-1.5:LRA=7"
    af_filters.append(loudnorm)

    filter_chain = ",".join(af_filters)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-i",
        input_path,
        "-t",
        str(duration),
        "-af",
        filter_chain,
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        out_path,
    ]

    run_ffmpeg(cmd)
    return out_path


# --------- TEMPO MATCHING (TIME-STRETCH NEXT CLIP) ----------
def tempo_match_clip(clip_path, source_bpm, target_bpm):
    if target_bpm <= 0 or source_bpm <= 0:
        return clip_path

    factor = target_bpm / source_bpm  # how much to speed up (or slow down) the clip
    print(f"\n⏱ Tempo match {os.path.basename(clip_path)}: {source_bpm:.2f} → {target_bpm:.2f} (factor {factor:.3f})")

    # ffmpeg atempo only supports 0.5–2.0 per filter; clamp for safety
    # for large differences you'd chain, but for most songs this is okay
    factor_clamped = max(min(factor, 2.0), 0.5)

    matched_path = clip_path.replace("_trimmed", "_tempo_matched")

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        clip_path,
        "-filter:a",
        f"atempo={factor_clamped}",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        matched_path,
    ]
    run_ffmpeg(cmd)

    return matched_path


# --------- MAIN PIPELINE WITH AUTOMATIC BEAT-MATCHED TRANSITIONS ----------
def trim_and_mix_beatmatched(json_path):
    with open(json_path, "r") as f:
        data = json.load(f)

    songs = data["songs"]
    output_name = data.get("output_file", "merged_output.mp3")
    final_raw_mix = os.path.join(OUTPUT_DIR, "temp_raw_mix.mp3")
    final_output_path = os.path.join(OUTPUT_DIR, output_name)

    print("\n============================")
    print("  PARALLEL DOWNLOADING")
    print("============================\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as exec_pool:
        list(exec_pool.map(download_audio, songs))

    print("\n============================")
    print("  TRIMMING + FADES + PER-CLIP NORMALIZATION")
    print("============================\n")

    # One trimmed clip per song
    trimmed_clips = []
    bpms = []

    for info in songs:
        clip = trim_audio(info)
        trimmed_clips.append(clip)
        bpm = detect_bpm(clip)
        bpms.append(bpm)

    if not trimmed_clips:
        print("No clips found. Check your JSON.")
        return

    print("\n============================")
    print("  BUILDING BEAT-MATCHED MIX")
    print("============================\n")

    # Use BPM of first song as global target BPM
    global_bpm = bpms[0]
    crossfade_beats = 8  # number of beats for each transition
    beat_duration = 60.0 / global_bpm
    crossfade_duration = beat_duration * crossfade_beats
    # clamp a bit so it's not insane for very slow songs
    crossfade_duration = max(2.0, min(crossfade_duration, 10.0))

    print(f"🎼 Global BPM: {global_bpm:.2f}")
    print(f"🔗 Crossfade duration (approx {crossfade_beats} beats): {crossfade_duration:.2f}s")

    # Start mix as first clip
    current_mix = trimmed_clips[0]

    # For each next clip: tempo-match → beat-matched crossfade
    for i in range(1, len(trimmed_clips)):
        next_clip = trimmed_clips[i]
        next_bpm = bpms[i]

        # Tempo-match NEXT clip to global BPM
        matched_next = tempo_match_clip(next_clip, source_bpm=next_bpm, target_bpm=global_bpm)

        mixed_output = os.path.join(OUTPUT_DIR, f"temp_mix_step_{i}.mp3")

        # acrossfade uses last d seconds of A and first d seconds of B
        filter_complex = f"[0:a][1:a]acrossfade=d={crossfade_duration}:c1=tri:c2=tri"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            current_mix,
            "-i",
            matched_next,
            "-filter_complex",
            filter_complex,
            "-acodec",
            "libmp3lame",
            "-b:a",
            "192k",
            mixed_output,
        ]
        run_ffmpeg(cmd)

        current_mix = mixed_output  # update chain

    # After loop, current_mix is our raw DJ-style mix
    os.replace(current_mix, final_raw_mix)

    print("\n============================")
    print("  FINAL MIX NORMALIZATION (LUFS)")
    print("============================\n")

    final_norm_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        final_raw_mix,
        "-af",
        "loudnorm=I=-14:TP=-1.5:LRA=7",
        "-acodec",
        "libmp3lame",
        "-b:a",
        "192k",
        final_output_path,
    ]
    run_ffmpeg(final_norm_cmd)

    print("\n🎉 BEAT-MATCHED MIX COMPLETED SUCCESSFULLY!")
    print(f"👉 Final file: {final_output_path}")


# --------- ENTRY POINT ----------
if __name__ == "__main__":
    trim_and_mix_beatmatched("bhoomika.json")
