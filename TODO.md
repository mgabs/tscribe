# Backlog
- [ ] record/play  --start  and --end parameters to start and stop automatically
- [ ] record --vad for voice audio detection (only record when voice is detected)
- [x] transcribe --diarize (offline voice embeddings + clustering with --names and tscribe label)
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


## Live meeting captions

- [x] Save caption preferences in shared config and expose app/menu settings.
- [x] Capture microphone and system audio together, retaining separate tracks.
- [ ] Validate echo cancellation with speakers, overlapping speech, and headphones.
- [ ] Handle output-device changes during a meeting.
- [x] Stream stable phrases with a provisional last phrase; keep capture independent of transcription.
- [x] Add a floating captions window using saved size and always-on-top preferences.
- [x] Save the caption draft and produce a final transcript after recording stops.
- [ ] Benchmark caption delay, quality, CPU, memory, and power on representative meetings.
- [ ] Add CLI live recording/caption streaming.
- [ ] Validate combined capture on real calls and improve stop-time draft coverage.
