"""Voice input: speech-to-text transcription (#363).

The chat assistant's mic button records a short clip in the browser and posts it here; this
module forwards it to a user-configured, OpenAI-compatible transcription endpoint
(``{stt_base_url}/audio/transcriptions`` — whisper.cpp server, Speaches, Groq whisper, ...)
and returns the recognised text. The endpoint is deliberately separate from the chat
provider (Ollama and friends have no STT), with its own base URL, model and write-only key.

Transcription only ever produces text that the user reviews before it is sent — Spoolman
never acts on a raw transcript on its own (that guardrail lives in the client, decision:
transcribe-then-review by default).
"""

import logging

import httpx

from spoolman.ai import AIConfig, AIRequestError

logger = logging.getLogger(__name__)

#: A short push-to-talk clip transcribes quickly, but local whisper on modest hardware is not
#: instant — give it room without hanging forever.
_STT_TIMEOUT = 60.0


async def transcribe(config: AIConfig, audio: bytes, *, filename: str, content_type: str) -> str:
    """Transcribe an audio clip via the configured STT endpoint; return the recognised text.

    Raises AIRequestError with a user-safe message on any failure (unconfigured, unreachable,
    HTTP error, unexpected response shape) so the endpoint can translate it cleanly.
    """
    if not config.stt_base_url:
        raise AIRequestError("No speech-to-text endpoint is configured.")
    if not config.stt_model:
        raise AIRequestError("No speech-to-text model is configured.")

    headers = {"Authorization": f"Bearer {config.stt_api_key}"} if config.stt_api_key else {}
    files = {"file": (filename, audio, content_type)}
    data = {"model": config.stt_model}
    async with httpx.AsyncClient(timeout=_STT_TIMEOUT, headers=headers) as client:
        try:
            response = await client.post(f"{config.stt_base_url}/audio/transcriptions", data=data, files=files)
        except httpx.TimeoutException as exc:
            raise AIRequestError(f"The speech-to-text endpoint timed out after {int(_STT_TIMEOUT)} s.") from exc
        except httpx.HTTPError as exc:
            raise AIRequestError(f"The speech-to-text endpoint is unreachable: {exc.__class__.__name__}.") from exc

    if response.status_code == httpx.codes.UNAUTHORIZED:
        raise AIRequestError("The speech-to-text endpoint rejected the API key (HTTP 401).")
    if response.status_code != httpx.codes.OK:
        detail = ""
        try:
            detail = str(response.json().get("error", {}).get("message", ""))[:200]
        except (ValueError, AttributeError):
            detail = response.text[:200]
        raise AIRequestError(f"The speech-to-text endpoint returned HTTP {response.status_code}. {detail}".strip())

    try:
        text = response.json()["text"]
    except (ValueError, KeyError, TypeError) as exc:
        raise AIRequestError("The speech-to-text endpoint returned an unexpected response shape.") from exc
    if not isinstance(text, str):
        raise AIRequestError("The speech-to-text endpoint returned no text.")
    return text.strip()
