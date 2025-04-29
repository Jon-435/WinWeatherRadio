#Python Imports
import subprocess
import threading
import queue
import time
import argparse
from hashlib import md5
from string import ascii_letters, digits
import os

# Third Party Imports
import numpy as np
import pyaudio
import pyttsx3
from pydub import AudioSegment
from pydub.playback import play
from EASGen import EASGen
from EAS2Text import EAS2Text

# User Settings
callsign = "JON435  "
pretone_file = "pretone.wav"
use_pretone = True
pretone_volume = -0.5

# Do NOT touch anything below here, unless there is something really wrong
chunk_size = 4000
sample_rate = 24000
converter = pyttsx3.init()
converter.setProperty('rate', 135)
converter.setProperty('volume', 0.95)

alert_queue = queue.Queue()
relayed_alerts = []

class ActiveAlert:
    def __init__(self, header, east_text, monitor_num, recorded_audio):
        self.header = header
        self.east_text = east_text
        self.monitor_num = monitor_num
        self.recorded_audio = recorded_audio
        self.eom_received = threading.Event()
        self.pretone_done = threading.Event()

def play_audio_segment_live(audio_segment):
    raw_data = audio_segment.raw_data
    sample_width = audio_segment.sample_width
    frame_rate = audio_segment.frame_rate
    channels = audio_segment.channels
    p = pyaudio.PyAudio()
    stream = p.open(format=p.get_format_from_width(sample_width),
                    channels=channels,
                    rate=frame_rate,
                    output=True)
    chunk = 1024
    for i in range(0, len(raw_data), chunk):
        stream.write(raw_data[i:i + chunk])
    stream.stop_stream()
    stream.close()
    p.terminate()

def encode_and_play(header, recorded_audio):
    eas_header = header
    header_segments = eas_header.split("-")
    header_segments[-2] = callsign
    new_eas_header = "-".join(header_segments)
    audio = AudioSegment(
        recorded_audio.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=1
    )
    print(f"Encoding with header: {new_eas_header}")
    alert = EASGen.genEAS(header=new_eas_header, attentionTone=False, audio=audio, mode="NWS", endOfMessage=True)
    filename = md5(audio.raw_data).hexdigest()
    EASGen.export_wav(f"{filename}.wav", alert)
    print(f"EAS alert encoded and saved as {filename}.wav!")
    print("Playing alert audio...")
    play(alert)
    print("Alert audio done playing!")

def play_pretone_and_tts(alert_obj):
    try:
        tts_text = f"May I have your attention please! An alert was just received on Monitor {alert_obj.monitor_num}. {alert_obj.east_text}. Please stand by. The alert is being processed and will be relayed shortly."
        tts_file = md5(tts_text.encode()).hexdigest()
        converter.save_to_file(tts_text, f'{tts_file}.mp3')
        converter.runAndWait()
        converter.stop()
        ffmpeg_command = [
            "ffmpeg", "-y",
            "-i", f"{tts_file}.mp3",
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", "1",
            f"{tts_file}.wav"
        ]
        subprocess.run(ffmpeg_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(f"{tts_file}.mp3")
        pretone = AudioSegment.from_wav(pretone_file) + pretone_volume
        print(f"[Monitor {alert_obj.monitor_num}] Playing pretone...")
        play_audio_segment_live(pretone)
        play_audio_segment_live(pretone)
        tts_wav = AudioSegment.from_wav(f"{tts_file}.wav")
        print(f"[Monitor {alert_obj.monitor_num}] Playing TTS announcement...")
        play_audio_segment_live(tts_wav)
        print(f"[Monitor {alert_obj.monitor_num}] TTS done.")
        os.remove(f"{tts_file}.wav")
        alert_obj.pretone_done.set()
    except Exception as e:
        print(f"Error with TTS: {e}")

def process_alert_queue():
    while True:
        if not alert_queue.empty():
            alert = alert_queue.get()
            print(f"--- Processing alert from Monitor {alert.monitor_num} ---")

            play_pretone_and_tts(alert)

            print(f"[Monitor {alert.monitor_num}] Waiting for EOM and pretone to finish...")
            alert.pretone_done.wait()
            alert.eom_received.wait()

            print(f"[Monitor {alert.monitor_num}] Starting alert playback...")
            encode_and_play(alert.header, alert.recorded_audio)

            print(f"[Monitor {alert.monitor_num}] Finished playback, waiting 2 seconds...")
            time.sleep(2)
        else:
            time.sleep(0.1)

def monitor_samedec(device_name, monitor_num):
    ffmpeg_command = [
        "ffmpeg",
        "-f", "dshow",
        "-i", f"audio={device_name}",
        "-f", "s16le",
        "-c:a", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "1",
        "-"
    ]
    print(f"[Monitor {monitor_num}] Launching ffmpeg for audio capture on device {device_name}...")
    ffmpeg_process = subprocess.Popen(
        ffmpeg_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0
    )
    samedec_process = subprocess.Popen(
        [".\\samedec", "-r", str(sample_rate)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0
    )
    print(f"[Monitor {monitor_num}] Monitoring audio for EAS SAME headers...")
    recording = False
    recorded_audio = np.empty(0, dtype=np.int16)
    current_alert = None

    def feed_audio_to_samedec():
        nonlocal recording, recorded_audio
        while True:
            data = ffmpeg_process.stdout.read(chunk_size)
            if not data:
                print(f"[Monitor {monitor_num}] ffmpeg process ended.")
                break
            try:
                samedec_process.stdin.write(data)
                samedec_process.stdin.flush()
            except BrokenPipeError:
                print(f"[Monitor {monitor_num}] SAME decoder pipe broken.")
                break

            samples = np.frombuffer(data, dtype=np.int16)
            if recording and current_alert:
                recorded_audio = np.append(recorded_audio, samples)
    threading.Thread(target=feed_audio_to_samedec, daemon=True).start()
    while True:
        line = samedec_process.stdout.readline()
        if not line:
            break
        line = line.decode(errors="ignore").strip()
        if "ZCZC-" in line:
            header = line.replace("EAS: ", "")
            alert_hash = md5(header.encode()).hexdigest()
            if alert_hash not in relayed_alerts:
                relayed_alerts.append(alert_hash)
                print(f"[Monitor {monitor_num}] SAME Header detected: {header}")
                decoded = EAS2Text(header)
                recording = True
                recorded_audio = np.empty(0, dtype=np.int16)

                current_alert = ActiveAlert(header, decoded.EASText, monitor_num, recorded_audio)
                alert_queue.put(current_alert)
        elif "NNNN" in line and current_alert:
            print(f"[Monitor {monitor_num}] EOM Detected.")
            recording = False
            # Finished recording
            current_alert.recorded_audio = recorded_audio
            current_alert.eom_received.set()
            current_alert = None

def main():
    parser = argparse.ArgumentParser(description="Weather Radio Live Patch")
    parser.add_argument("-s", "--soundcard", action="append", required=True, help="Soundcard input device name")
    args = parser.parse_args()
    if callsign:
        if len(callsign) != 8:
            print("Callsign must be exactly 8 characters long. Exiting.")
            return
        for i in callsign:
            if i not in ascii_letters + digits + "-+?()[]._,/ ":
                print("Callsign invalid. Exiting.")
                return
        print(f"Callsign is valid: {callsign}")
    threading.Thread(target=process_alert_queue, daemon=True).start()
    for idx, device_name in enumerate(args.soundcard, start=1):
        threading.Thread(target=monitor_samedec, args=(device_name, idx), daemon=True).start()
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
