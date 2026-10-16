# SpeexDSP echo cancellation subset

Unmodified C sources and supporting headers from SpeexDSP 1.2.1:
https://downloads.xiph.org/releases/speex/speexdsp-1.2.1.tar.gz

Upstream archive SHA-256:
`8c777343e4a6399569c72abc38a95b24db56882c83dbdb6c6424a5f4aeb54d3d`

Only the floating-point MDF echo canceller and Kiss FFT backend are compiled.
`speexdsp_config_types.h` is generated locally using standard fixed-width types;
no other upstream files are modified. See COPYING for copyright and license.
The app bundles that notice and the per-file notices in THIRD_PARTY_NOTICES.txt
with the compiled library.

Build with `python packaging/macos/build_audio_dsp.py`. A C compiler is needed
only on build/development machines, not on Macs using the distributable app.
