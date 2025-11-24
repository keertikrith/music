Using Homebrew (recommended):
brew install ffmpeg

Enable all common codecs:
brew install ffmpeg --with-libvpx --with-libvorbis --with-opus

Verify installation:
ffmpeg -version



🪟 Windows
Option 1 — Using Chocolatey (easy):
choco install ffmpeg

Option 2 — Manual installation:

Go to: https://ffmpeg.org/download.html

Under Windows, choose a build (e.g., Gyan.dev or BtbN).

Download the latest full build ZIP.

Extract it to a folder, e.g.:

C:\ffmpeg


Add FFmpeg to your PATH:

Open Environment Variables

Edit Path

Add:

C:\ffmpeg\bin


Restart your terminal.

Verify:
ffmpeg -version
