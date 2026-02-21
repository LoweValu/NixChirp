# NixChirp Roadmap

## Bug Fixes

- [ ] **Virtual camera EINVAL error** — v4l2loopback virtual camera output fails with an EINVAL ioctl error. Window capture, chroma key, and transparent modes all work. Likely a format negotiation issue with the V4L2 device.
- [ ] **Virtual camera unavailable in Flatpak** — The Flatpak sandbox doesn't include `pkexec`, so the "Load kernel module" button in Output settings does nothing. Users must load `v4l2loopback` on the host manually before launching.

## Testing Needed

- [ ] **APNG avatar support** — The decoder handles APNG via PyAV but this has not been tested with real animated PNG files. Need to verify playback, transparency, and loop behavior.
- [ ] **WebM avatar support** — VP8/VP9 WebM decoding is implemented (including alpha channel) but untested with real files. Need to verify playback, transparency, and performance.

## Stretch Goals

- [ ] Expression blending — blend multiple states together for combined expressions
- [ ] Physics / bounce — procedural bounce and jiggle on state transitions
- [ ] Plugin system — let users extend NixChirp with custom behaviors
- [ ] Twitch / YouTube integration — react to chat events, subs, donations
- [ ] Multi-layer compositing — stack multiple avatar layers (body, face, accessories)
- [ ] Sound-reactive effects — visual effects driven by audio frequency analysis
- [ ] Remote control — WebSocket API for external control (e.g. Stream Deck)
- [ ] Windows / macOS support
