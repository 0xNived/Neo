# Voice

Install with `pip install -e ".[voice]"`. This installs runtime libraries only; speech/TTS model weights are downloaded only when you explicitly select a model. Use faster-whisper on the RTX 3080 and keep TTS on CPU. Implement microphone capture, VAD, and barge-in in `apps/voice`.
