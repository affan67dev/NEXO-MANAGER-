import subprocess,time

WAKE_WORDS=["hey nexo","hey nex","hi nexo","हे नेक्सो","हे नेक्सो"]

def listen():
    try:
        p=subprocess.run(["termux-speech-to-text"],capture_output=True,text=True,timeout=15)
        return p.stdout.strip().lower()
    except:
        return ""

def speak(text):
    print("NEXO:",text)
    subprocess.run(["termux-tts-speak",text.replace("NEXO","Nexo")],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def popup(text):
    subprocess.run(["termux-toast","-g","top",text],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def wake(text):
    return any(x in text for x in WAKE_WORDS)

def main():
    print("🤖 NEXO Voice Agent started")
    print("🎙️ Say: Hey Nexo")
    while True:
        try:
            text=listen()
            if not text:
                time.sleep(.5)
                continue
            print("USER:",text)
            if wake(text):
                popup("NEXO activated")
                speak("Hello! I am Nexo. What can I help you with?")
                command=listen()
                if command:
                    print("COMMAND:",command)
                    speak("I heard you. I am ready to help.")
                    popup("NEXO ready")
            time.sleep(.3)
        except KeyboardInterrupt:
            print("\nNEXO stopped.")
            break
        except Exception as e:
            print("ERROR:",e)
            time.sleep(1)

if __name__=="__main__":
    main()
