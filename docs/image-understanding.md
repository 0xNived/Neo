# Image understanding and file imports

Neo should not treat an image URL, a local file path, and image understanding as
the same thing. Saving a reference is inexpensive and private; reading bytes or
sending pixels to a vision model is an explicit import operation.

## Recommended pipeline

Image, PDF, or document goes through: explicit upload or import; local blob
storage with hash and MIME validation; extractor worker; provenance-rich
Organizer item and chunks; hybrid retrieval with the source attachment.

For images, the extractor performs OCR, a vision caption, and optionally an
EXIF summary. Documents use text/page extraction and OCR where needed. The
resulting text and captions are chunked and embedded. Raw bytes and raw paths
are never embedded.

Store original bytes outside PostgreSQL, for example in .neo-data/uploads or an
S3-compatible object store. PostgreSQL stores metadata, extracted text, chunk
references, hashes, and permissions. Do not send raw files to an LLM prompt or
vector database.

## First implementation target

1. Upload or import only after the owner selects a file.
2. Validate MIME type, file size, and hash-deduplicate the blob.
3. Create an Organizer item with source, timestamp, filename, and import
   status.
4. Run OCR and vision description in a background worker.
5. Embed extracted text/caption, never a raw file path or binary.
6. Show the attachment, extracted summary, and source metadata in Organizer.

Local Ollama is the best default for Neo's private setup. Run a vision-capable
model separately from the chat model, for example qwen2.5vl:7b on a capable
GPU. A hosted vision provider can use the same adapter interface, but must be
opt-in because the image leaves the machine.

Text-only models can discuss a filename or user-provided description, but they
cannot understand pixels. Actual image questions require a configured vision
model.
