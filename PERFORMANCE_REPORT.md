# Mantice Performance Profiling Report

## Executive Summary

**Test Configuration:**
- **Sample Rate:** 48kHz (render mode)
- **Duration:** 6 seconds per preset
- **Chunk Size:** 4096 samples
- **Total Samples:** 288,000 (per stereo pair)

**Baseline Performance (6s renders @ 48kHz):**

| Mode   | Render Time | Realtime Factor | Peak Level | CPU Profile                          |
|--------|-------------|-----------------|------------|--------------------------------------|
| FM     | 0.271s      | **22.17x**      | 0.0224     | Balanced (compression + synthesis)   |
| Sub    | 0.311s      | **19.30x**      | 0.0309     | Waveform generation dominant         |
| Gran   | 0.275s      | **21.83x**      | 0.0423     | Sample loading + grain spawning      |
| Multi  | 0.580s      | **10.35x**      | 0.0581     | All synthesis modes combined         |

**Key Findings:**
- ✅ **All modes render faster than realtime** (10x-22x realtime speed)
- ✅ **FM synthesis is most efficient** (22x realtime, lightest CPU load)
- ⚠️ **Multi-layer rendering is ~2x slower** than single layer (but still 10x realtime)
- ⚠️ **Master compression dominates CPU** (~45-50% of total time across all modes)

---

## Detailed Analysis

### 1. FM Synthesis (Fastest - 22.17x Realtime)

**Top 5 Bottlenecks:**
1. **master_processing.py:134 (_compress_stereo)** - 120ms (44%)
   - Stereo compression/limiting on the master bus
2. **streaming_engine.py:268 (StreamingLayer.next_chunk)** - 40ms (15%)
   - FM oscillator chunk generation
3. **_signaltools.py:4957 (sosfilt)** - 18ms (7%)
   - IIR filter processing (lowpass/highpass)
4. **streaming_engine.py:636 (_apply_balance)** - 10ms (4%)
   - Stereo balance/pan processing
5. **streaming_engine.py:585 (_compute_pan)** - 5ms (2%)
   - Pan computation (quadrant system)

**Observations:**
- FM synthesis itself is lightweight (~15% of total time)
- Master compression dominates (44%)
- Filter processing is well-optimized (only 7%)

---

### 2. Subtractive Synthesis (19.30x Realtime)

**Top 5 Bottlenecks:**
1. **master_processing.py:134 (_compress_stereo)** - 118ms (38%)
   - Master compression (same as FM)
2. **streaming_engine.py:492 (StreamingSubtractiveLayer.next_chunk)** - 17ms (5.5%)
   - Chunk generation overhead
3. **streaming_engine.py:441 (_waveform)** - 64ms (21%)
   - **CRITICAL**: Saw/square waveform generation with PolyBLEP anti-aliasing
4. **streaming_engine.py:463 (_polyblep)** - 20ms (6.5%)
   - PolyBLEP discontinuity suppression
5. **_signaltools.py:4957 (sosfilt)** - 29ms (9%)
   - Filter processing

**Observations:**
- **Waveform generation is the bottleneck** (21% of time)
- PolyBLEP anti-aliasing adds overhead (6.5%) but is necessary for quality
- Master compression still significant (38%)

---

### 3. Granular Synthesis (21.83x Realtime)

**Top 5 Bottlenecks:**
1. **master_processing.py:134 (_compress_stereo)** - 114ms (42%)
   - Master compression (consistent across modes)
2. **granular_layer.py:58 (__init__)** - 65ms (24%)
   - **CRITICAL**: Granular layer initialization (sample loading + resampling)
3. **soundfile.py:1396 (_cdata_io)** - 32ms (12%)
   - WAV/OGG file loading (part of initialization)
4. **_signaltools.py:3866 (resample_poly)** - 12ms (4%)
   - Sample rate conversion during initialization
5. **granular_layer.py:208 (next_chunk)** - 23ms (8%)
   - Grain synthesis chunk generation
6. **granular_layer.py:142 (_spawn_grain_at)** - 20ms (7%)
   - Grain spawning logic

**Observations:**
- **Sample loading/resampling is expensive** (24% + 12% = 36% during init)
- Grain synthesis itself is efficient (8%)
- Master compression still dominates runtime (42%)

---

### 4. Multi-Layer (10.35x Realtime)

**Top 5 Bottlenecks:**
1. **master_processing.py:134 (_compress_stereo)** - 151ms (26%)
   - Master compression (more audio to compress)
2. **streaming_engine.py:492 (Sub.next_chunk)** - 99ms (17%)
   - Subtractive layer rendering
3. **streaming_engine.py:268 (FM.next_chunk)** - 85ms (15%)
   - FM layer rendering
4. **streaming_engine.py:441 (_waveform)** - 67ms (12%)
   - Subtractive waveform generation
5. **granular_layer.py:58 (__init__)** - 72ms (12%)
   - Granular initialization

**Observations:**
- **Multi-layer is ~2x slower** (10.35x vs 20x realtime for single layers)
- Each layer adds roughly linear overhead
- Master compression percentage drops (26% vs 40%+) because synthesis time increases

---

## Performance Bottlenecks Summary

### 🔥 Critical Bottlenecks (Optimization Opportunities)

1. **Master Compression (_compress_stereo)** — 40-50% of CPU time
   - Runs on every chunk (71 times per 6s render)
   - Uses `np.clip` and `np.maximum` in a loop
   - **Potential optimization**: Vectorize the compression loop, reduce clip operations

2. **Subtractive Waveform Generation (_waveform + _polyblep)** — 27% of Sub CPU time
   - PolyBLEP anti-aliasing is expensive but necessary
   - Saw/square waveforms naturally generate more harmonics than sine
   - **Potential optimization**: Pre-compute waveform cycles, use lookup tables for common cases

3. **Granular Sample Loading (soundfile + resample_poly)** — 36% of Gran init time
   - Happens once during initialization, not per-chunk
   - Resampling is expensive for large samples
   - **Potential optimization**: Cache resampled samples, lazy-load samples

4. **IIR Filter Processing (sosfilt)** — 7-9% of CPU time
   - Already well-optimized (uses SciPy's C backend)
   - Minimal optimization potential

---

## Recommendations (Priority Order)

### 1. **Optimize Master Compression** (High Impact)
   - **Why**: Consumes 40-50% of CPU across all modes
   - **How**: Vectorize the compression loop in `master_processing.py:134`
   - **Expected Gain**: 20-30% speedup across all modes

### 2. **Pre-compute Subtractive Waveforms** (Medium Impact)
   - **Why**: Waveform generation is 27% of subtractive CPU time
   - **How**: Use wavetable synthesis for saw/square instead of per-sample PolyBLEP
   - **Expected Gain**: 15-20% speedup for subtractive mode

### 3. **Cache Resampled Samples for Granular** (Low Impact)
   - **Why**: Sample loading is 36% of granular init time
   - **How**: Cache resampled samples in memory across renders
   - **Expected Gain**: Faster initialization, minimal runtime impact

### 4. **Profile Long Renders (30s+)** (Investigation)
   - **Why**: Memory allocation patterns may differ for long renders
   - **How**: Run profiler with 30s-60s durations, check for memory leaks
   - **Expected Gain**: Better understanding of segmented rendering performance

---

## Next Steps

1. ✅ **Baseline established** - All modes profiled
2. ⏳ **Analyze bottlenecks** - Report created with findings
3. ⏳ **Implement optimizations** - Focus on master compression first
4. ⏳ **Memory profiling** - Check long-render memory patterns
5. ⏳ **Document findings** - Update README with performance characteristics

---

## Tool Usage

```bash
# Profile all modes (6s renders)
python profile_engine.py --compare

# Profile single mode
python profile_engine.py --mode fm

# Profile longer duration
python profile_engine.py --mode gran --duration 30

# Include memory profiling (requires memory_profiler)
python profile_engine.py --mode fm --memory
```

---

## Baseline Metrics (For Future Comparison)

**Hardware**: Windows, 12 CPU cores  
**Python**: 3.x  
**NumPy**: Latest  

| Mode   | 6s Render Time | Realtime Factor |
|--------|----------------|-----------------|
| FM     | 0.271s         | 22.17x          |
| Sub    | 0.311s         | 19.30x          |
| Gran   | 0.275s         | 21.83x          |
| Multi  | 0.580s         | 10.35x          |

**Target**: Maintain >10x realtime for multi-layer, >15x for single-layer after optimizations.
