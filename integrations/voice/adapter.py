import subprocess

def speech_to_text():
    try:
        r=subprocess.run(["termux-speech-to-text"],capture_output=True,text=True,timeout=60)
        return r.stdout.strip()
    except Exception:
        return ""

def text_to_speech(text):
    try:
        subprocess.run(["termux-tts-speak",text],timeout=30)
        return True
    except Exception:
        return False
