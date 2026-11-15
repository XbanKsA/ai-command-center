# Wake-word model

Put the trained **`hey_kageon.onnx`** in this folder. Kageon picks it up automatically on the next start
(the startup banner then says `Voice : ON (say: Hey Kageon)`).

Until the file exists, voice wake-up uses a temporary built-in openWakeWord phrase. The banner and the log
say which one; no ready-made model exists for a new name, so a custom one has to be trained.

## How the model is made

openWakeWord trains a small model (~200 KB) from **synthetic** speech: a text-to-speech engine says
"hey kageon" thousands of times in different voices, the clips are mixed with noise and music, and a
classifier learns to spot the phrase. The official example is
`notebooks/automatic_model_training.ipynb` in https://github.com/dscripka/openWakeWord and runs on a free
Google Colab GPU in about an hour.

Tips:
- If the TTS pronounces the name wrong, train with a phonetic spelling (for example `hey kah geh on`);
  the file name can still be `hey_kageon.onnx`.
- Too many accidental wake-ups -> raise `WAKE_THRESHOLD` in `.env` (e.g. 0.6). Missed wake-ups -> lower it.
- To use a model stored somewhere else, set `WAKE_WORD_MODEL=path\to\model.onnx` in `.env`.
