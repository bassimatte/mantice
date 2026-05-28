# Memory Profiling Results

## Summary

**Test Configuration:**
- **Duration:** 30 seconds @ 48kHz
- **Tool:** Python tracemalloc (built-in)
- **Chunk Size:** 4096 samples

## Key Findings

### ✅ **Memory Usage is Linear and Predictable**

All synthesis modes show **perfectly linear memory growth** during rendering:
- No memory leaks detected
- Memory scales linearly with duration
- Peak memory ≈ Audio buffer size + 22MB overhead

### Memory Usage by Mode (30s render)

| Mode | Init Memory | Render Memory | Peak Memory | Audio Size |
|------|-------------|---------------|-------------|------------|
| **FM** | 667 KB | 44.03 MB | 44.68 MB | 21.97 MB |
| **Sub** | 658 KB | 44.02 MB | 44.67 MB | 21.97 MB |
| **Gran** | 4.86 MB | 44.04 MB | 48.91 MB | 21.97 MB |
| **Multi** | 5.08 MB | 44.03 MB | 49.12 MB | 21.97 MB |

### Observations

1. **Init Memory:**
   - FM/Sub: ~660 KB (minimal)
   - Gran/Multi: ~5 MB (due to sample loading + resampling)
   - Gran initialization includes 4.2MB for sample resampling

2. **Render Memory:**
   - **Constant 44 MB** across all modes (for 30s render)
   - Scales linearly: ~1.47 MB per second of audio
   - Formula: `Render Memory ≈ (duration * 48000 * 2 channels * 4 bytes) * 2`
   - The 2x factor comes from chunk accumulation before vstack

3. **Peak Memory:**
   - FM/Sub: 44.7 MB (render memory only)
   - Gran/Multi: 49 MB (render memory + sample buffers)
   - Peak = Current + small overhead (~0.5 MB)

4. **Memory Over Time:**
   ```
   Time (s)  |  FM Memory  |  Gran Memory
   ---------|-------------|-------------
   0.0      |  0 MB       |  0 MB
   3.0      |  2.9 MB     |  7.2 MB  (sample loading)
   6.0      |  5.1 MB     |  9.4 MB
   12.0     |  9.5 MB     |  13.7 MB
   18.0     |  13.9 MB    |  18.1 MB
   24.0     |  18.3 MB    |  22.6 MB
   30.0     |  22.7 MB    |  26.9 MB  (before vstack)
   30.0     |  44.7 MB    |  48.9 MB  (after vstack)
   ```
   - Memory grows linearly at ~0.75 MB/s
   - Final vstack doubles memory (copies chunks into contiguous array)

5. **Top Memory Allocations:**
   - **22 MB:** `master_processing.py:28` — Chunk accumulation list
   - **22 MB:** `shape_base.py:290` — vstack operation (final concatenation)
   - **4.2 MB:** `_signaltools.py:5063` — Granular sample resampling (Gran/Multi only)
   - **340 KB:** `streaming_engine.py:1287` — Engine state buffers

---

## Analysis

### ✅ No Memory Leaks
- Memory growth is perfectly linear
- No accumulating garbage or leaked references
- Garbage collection is working correctly

### ✅ Efficient Memory Usage
- 30s @ 48kHz stereo = 21.97 MB audio data
- Peak memory: 44-49 MB (only 2x audio size)
- Overhead: ~22 MB for chunk accumulation (unavoidable for streaming)

### Optimization Opportunities

1. **Streaming to File (Future Enhancement)**
   - Current: Accumulate all chunks in memory, then vstack
   - Alternative: Write chunks directly to file stream
   - **Benefit**: Would reduce peak memory from 44MB to ~2MB for long renders
   - **Trade-off**: Slightly slower I/O, more complex API

2. **Granular Sample Caching (Low Priority)**
   - Gran/Multi spend 4.2 MB on sample resampling during init
   - Could cache resampled samples across renders
   - **Benefit**: Faster initialization, lower memory footprint
   - **Trade-off**: Global cache management complexity

3. **Segmented Rendering (Already Implemented for Streaming)**
   - The streaming engine already supports segmented rendering (MANT-1)
   - For web API, renders are sent in 10s segments
   - This keeps memory constant regardless of total duration

---

## Recommendations

### For Current Implementation: ✅ **No Changes Needed**
- Memory usage is healthy and predictable
- No leaks or inefficiencies detected
- Linear scaling is optimal for the architecture

### For Future Enhancements:

1. **Long Renders (>60s)** — Consider streaming to file
   - Would reduce peak memory from 2x duration to constant ~2MB
   - Useful for offline rendering mode

2. **Web Streaming** — Already optimal
   - Segmented rendering keeps memory constant
   - No memory issues for streaming mode

3. **Sample Caching** — Low priority
   - Only benefits granular presets
   - Saves ~4MB and speeds up initialization
   - Not worth the complexity for now

---

## Conclusion

**Memory usage is excellent:**
- ✅ No leaks
- ✅ Linear scaling
- ✅ Efficient (2x audio size overhead)
- ✅ Segmented rendering available for long renders

**No optimization needed** — memory management is already production-ready.
