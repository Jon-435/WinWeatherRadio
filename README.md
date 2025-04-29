# WinWeatherRadio

A Python-based system that monitors multiple soundcards for SAME (Specific Area Message Encoding) EAS alerts, decodes them using [SAMEDEC](https://github.com/joshuabarnes/samedec), and relays the alerts sequentially with an optional pretone to the computer speakers.
This system is written for a Windows-based system, however it could be ported over to Linux or MacOS if you put some work into it

## Features

- Monitors multiple input audio devices for SAME headers
- Automatically records and processes alerts
- Sequential playback: only one alert plays at a time
- Pretone and TTS announcement which includes monitor source and decoded text
- Uses `ffmpeg` and `samedec` for audio handling and SAME decoding

---

## Requirements

- Python 3
- [ffmpeg](https://ffmpeg.org/) binary installed and added to your system PATH or working directory
- [samedec](https://github.com/joshuabarnes/samedec) binary installed and added to your system PATH or working directory
- At least one avaliable soundcound input (could be a physical line in or a virtual audio cable)

### Python Dependencies

Install with:

```pip install numpy pyaudio pyttsx3 pydub EASGen EAS2Text```
