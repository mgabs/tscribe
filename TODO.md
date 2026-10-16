Uncommitted
- [ ] record/play  --start  and --end parameters to start and stop automatically
- [ ] record --vad for voice audio detection (only record when voice is detected)
- [x] transcribe --diarize (offline VAD + clustering with --names and tscribe label)
- [ ] transcribe --live transcription or transcription overlapped (ie 30s) delay with recording
- [ ] ability to tag or add comment to clips for search
- [ ] better examples of using with claude code (blog or x post)
- [ ] alias command `list` to `ls`
- [ ] store recordings as .mp3?
- [ ] webui with `serve`
- [x] add `rm` / `clean` command to manage old recordings (`tscribe clean [--30]`)
- [x] macOS menu bar status item app (`tscribe app [--install-desktop]`)


## Native macOS app and transcription engine

- [ ] Evaluate WhisperKit as a replacement for the bundled Python transcription worker only after validating:
  - Transcription quality against faster-whisper on the same representative recordings, including different languages, accents, noise levels, and overlapping speech.
  - Performance on supported Apple Silicon Macs: model loading, first-run downloads, transcription speed, peak memory, and energy use.
  - Feature parity: language detection/selection, model choices, timestamps, TXT/JSON/SRT/VTT export, progress reporting, speaker grouping/names, configuration, CLI integration, and offline behavior after model download.
- [ ] Record benchmark results and migration tradeoffs before choosing a native transcription engine.
