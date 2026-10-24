# Timeline Schema & Specification

The IncuBrix Timeline format represents an edited video composition as pure, deterministic data.
It is defined and validated against JSON Schema Draft 7 and serialized into canonical JSON.

---

## 1. Top-Level Timeline Object

```json
{
  "version": "1.0",
  "timeline_hash": "2ed9b8ca44e0ead762c026cc373a3e35421bfd8c3e7d9db1837fa70a80891f15",
  "duration_us": 254200000,
  "duration_s": 254.2,
  "segments": [...],
  "captions": [...],
  "music": [...],
  "surviving_words": [...]
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | Timeline schema version (`"1.0"`). |
| `timeline_hash` | string | Canonical SHA-256 hash computed over normalized JSON segments, captions, and music. Guarantees 100% determinism. |
| `duration_us` | integer | Total duration of the edited timeline in integer microseconds. |
| `duration_s` | float | Total duration in seconds (`duration_us / 1,000,000`). |
| `segments` | array | Ordered list of surviving video/audio segments. |
| `captions` | array | Captions overlay items positioned along the edited timeline. |
| `music` | array | Background music overlay tracks. |
| `surviving_words` | array | Words from original transcript that survived all cuts, with mapped timeline timestamps. |

---

## 2. Segments (`Segment`)

A `Segment` defines a contiguous slice of source media played on the timeline.

```json
{
  "segment_id": 0,
  "src_start_us": 30000000,
  "src_end_us": 60000000,
  "speed_factor": 2.0,
  "output_duration_us": 15000000,
  "audio_muted": false,
  "audio_bleeped": false
}
```

### Mathematical Invariants
1. **Output Duration Formula**:
   $$\text{output\_duration\_us} = \text{round}\left( \frac{\text{src\_end\_us} - \text{src\_start\_us}}{\text{speed\_factor}} \right)$$
2. **Timeline Sum Invariant**:
   $$\text{duration\_us} = \sum_{s \in \text{segments}} s.\text{output\_duration\_us}$$
3. **Contiguity Invariant**:
   Adjacent segments represent distinct source time ranges or speed regimes. Overlapping cuts are merged during `fold()`.

---

## 3. Captions (`TimelineCaption`)

Captions bind strictly to immutable word identifiers from the source transcript.

```json
{
  "caption_id": "cap_001",
  "text": "Welcome!",
  "word_id_start": "w0000",
  "word_id_end": "w0003",
  "output_start_us": 12000000,
  "output_end_us": 14000000,
  "style": {
    "color": "#ffffff",
    "font_size": 24,
    "position": "bottom_center"
  }
}
```

### Invariants & Rules
* **Content Anchoring**: The caption start/end times (`output_start_us`, `output_end_us`) are dynamically computed from the timeline position of `word_id_start` and `word_id_end`.
* **Cut Propagation**: If words $w_{0000} \dots w_{0003}$ are cut from the video, the caption is omitted from the folded timeline. If that cut is restored via `RevokeOp` or `Undo`, the caption reappears in full.
* **Minimum Display Duration (R-CAP-02)**: During ASS subtitle rendering, caption durations compressed by speedup are clamped to $\ge 0.7\text{ s}$ for human readability.

---

## 4. Background Music (`TimelineMusic`)

```json
{
  "music_url": "default_music.mp3",
  "duck_level_db": -18.0,
  "loop": true
}
```

* Defines background audio ducked automatically under active speech intervals by `duck_level_db` (default: `-18.0 dB`).

---

## 5. Canonical SHA-256 Timeline Hasher

The `timeline_hash` is computed as:
```python
import hashlib, json

canonical_doc = {
    "duration_us": timeline.duration_us,
    "segments": [asdict(s) for s in timeline.segments],
    "captions": [asdict(c) for c in timeline.captions],
    "music": [asdict(m) for m in timeline.music],
}
json_bytes = json.dumps(canonical_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
timeline_hash = hashlib.sha256(json_bytes).hexdigest()
```
This guarantees identical timeline representations yield the identical cryptographic hash regardless of execution environment.
