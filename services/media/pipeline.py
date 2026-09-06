import shutil
def ffmpeg_available():
    return shutil.which("ffmpeg") is not None
