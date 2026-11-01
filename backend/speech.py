"""Text to speech with Azure AI Speech (REST). Returns MP3 bytes."""
import os
from xml.sax.saxutils import escape

import httpx

DEFAULT_VOICE = "ar-EG-SalmaNeural"


def is_configured() -> bool:
    return bool(os.getenv("AZURE_SPEECH_KEY") and os.getenv("AZURE_SPEECH_REGION"))


def synthesize(text: str) -> bytes:
    region = os.environ["AZURE_SPEECH_REGION"]
    voice = os.getenv("AZURE_SPEECH_VOICE", DEFAULT_VOICE)
    lang = "-".join(voice.split("-")[:2])  # "ar-EG-SalmaNeural" -> "ar-EG"
    ssml = (
        f"<speak version='1.0' xml:lang='{lang}'><voice name='{voice}'>"
        f"<prosody rate='-5%'>{escape(text)}</prosody></voice></speak>"
    )
    resp = httpx.post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        headers={
            "Ocp-Apim-Subscription-Key": os.environ["AZURE_SPEECH_KEY"],
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "amina-voice-agent",
        },
        content=ssml.encode("utf-8"),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.content
