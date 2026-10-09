class FasterWhisperStt:
    """Lazy local GPU STT adapter; model weights download on first explicit use."""

    def __init__(
        self,
        model_name: str = "distil-small.en",
        device: str = "cuda",
        compute_type: str = "int8_float16",
    ):
        self.model_name, self.device, self.compute_type = (
            model_name,
            device,
            compute_type,
        )
        self._model = None

    async def transcribe(self, audio: bytes) -> str:
        raise NotImplementedError(
            "Connect microphone capture and WAV decoding before invoking local STT."
        )
