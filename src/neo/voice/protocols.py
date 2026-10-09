from typing import Protocol


class SpeechToText(Protocol):
    async def transcribe(self, audio: bytes) -> str: ...


class TextToSpeech(Protocol):
    async def stream(self, text: str): ...
