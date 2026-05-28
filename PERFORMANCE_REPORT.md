# Mantice Performance Profiling Report

## Executive Summary

**Test Configuration:**
- **Sample Rate:** 48kHz (render mode)
- **Duration:** 6 seconds per preset
- **Chunk Size:** 4096 samples
- **Total Samples:** 288,000 (per stereo pair)

**Baseline Performance (Before Optimization):**

| Mode   | Render Time | Realtime Factor | Peak Level |
|--------|-------------|-----------------|------------|
| FM     | 0.271s      | 22.17x          | 0.0224     |
| Sub    | 0.311s      | 19.30x          | 0.0309     |
| Gran   | 0.275s      | 21.83x          | 0.0423     |
| Multi  | 0.580s      | 10.35x          | 0.0581     |

**Optimized Performance (After Master Compression Optimization):**

| Mode   | Render Time | Realtime Factor | Improvement | Peak Level |
|--------|-------------|-----------------|-------------|------------|
| FM     | **0.080s**  | **75.17x** ⚡    | **+239%**   | 0.0224     |
| Sub    | **0.115s**  | **51.98x** ⚡    | **+170%**   | 0.0309     |
| Gran   | **0.102s**  | **59.09x** ⚡    | **+170%**   | 0.0423     |
| Multi  | **0.252s**  | **23.80x** ⚡    | **+130%**   | 0.0581     |

**Test Suite Performance:**
- Quick test runtime: 142s → **105s** (26% faster)
- All 314 tests pass ✅

**Key Achievement:**
- ✅ **2-3x faster rendering** across all synthesis modes
- ✅ **70x+ realtime for FM synthesis** (was 22x)
- ✅ **Multi-layer now 24x realtime** (was 10x)
- ✅ **No audio quality degradation** (all tests pass)

---

## Optimization Details

### What Was Optimized

**Master Compression Parameter Pre-Computation**

**Before:**
```python
# _compress_stereo() called 71 times per 6s render
# Each call parsed config dict and computed:
- threshold_db → threshold (exponential)
- makeup_db → makeup (exponential)
- attack_ms → attack_coef (exponential)
- release_ms → release_coef (exponential)
- 6 dict.get() calls
- Multiple float() conversions
```

**After:**
```python
# MasterProcessor.__init__() pre-computes once:
self._comp_threshold = 10 ** (threshold_db / 20.0)
self._comp_makeup = 10 ** (makeup_db / 20.0)
self._comp_attack_coef = exp(-1.0 / ...)
self._comp_release_coef = exp(-1.0 / ...)
self._comp_enabled = ratio > 1.01 or abs(makeup_db) >= 0.1

# process() inlines compression logic:
- Direct access to pre-computed values
- No config dict parsing
- No repeated exponential computations
```

**Why This Works:**
- Master compression parameters never change during a render
- Computing them 71 times was pure waste
- Pre-computing + inlining eliminated ~150ms overhead

---

## Detailed Benchmark Results

### 1. FM Synthesis (Fastest - 75.17x Realtime)

**Performance:**
- Render Time: 0.080s (was 0.271s)
- **Improvement: +239% (3.4x faster)**
- Master compression overhead: ELIMINATED

**Top 5 Bottlenecks (After Optimization):**
1. **streaming_engine.py:268 (StreamingLayer.next_chunk)** - 23ms (29%)
   - FM oscillator chunk generation
2. **_signaltools.py:4957 (sosfilt)** - 10ms (13%)
   - IIR filter processing
3. **streaming_engine.py:636 (_apply_balance)** - 5ms (6%)
   - Stereo balance/pan processing
4. **streaming_engine.py:585 (_compute_pan)** - 3ms (4%)
   - Pan computation
5. **streaming_engine.py:1608 (next_chunk)** - 6ms (8%)
   - Engine overhead

**Observations:**
- Master compression no longer dominates (was 44%, now negligible)
- FM synthesis is now the bottleneck (29%)
- Further optimization would target FM oscillator

---

### 2. Subtractive Synthesis (51.98x Realtime)

**Performance:**
- Render Time: 0.115s (was 0.311s)
- **Improvement: +170% (2.7x faster)**

**Top 5 Bottlenecks:**
1. **streaming_engine.py:441 (_waveform)** - 42ms (37%)
   - Saw/square waveform generation with PolyBLEP
2. **streaming_engine.py:463 (_polyblep)** - 13ms (11%)
   - PolyBLEP anti-aliasing
3. **_signaltools.py:4957 (sosfilt)** - 18ms (16%)
   - Filter processing
4. **streaming_engine.py:492 (next_chunk)** - 11ms (10%)
   - Layer chunk generation overhead

**Observations:**
- Waveform generation is now the primary bottleneck (37%)
- Master compression overhead eliminated
- PolyBLEP is necessary for quality but expensive

---

### 3. Granular Synthesis (59.09x Realtime)

**Performance:**
- Render Time: 0.102s (was 0.275s)
- **Improvement: +170% (2.7x faster)**

**Top 5 Bottlenecks:**
1. **granular_layer.py:58 (__init__)** - 52ms (51%)
   - Sample loading + resampling (initialization)
2. **soundfile.py:1396 (_cdata_io)** - 28ms (27%)
   - WAV/OGG file I/O
3. **_signaltools.py:4957 (sosfilt)** - 8ms (8%)
   - Filter processing
4. **granular_layer.py:208 (next_chunk)** - 12ms (12%)
   - Grain synthesis

**Observations:**
- Initialization dominates (51%)
- Runtime grain synthesis is efficient (12%)
- Master compression overhead eliminated

---

### 4. Multi-Layer (23.80x Realtime)

**Performance:**
- Render Time: 0.252s (was 0.580s)
- **Improvement: +130% (2.3x faster)**

**Top 5 Bottlenecks:**
1. **streaming_engine.py:1608 (next_chunk)** - 13ms (5%)
2. **streaming_engine.py:492 (Sub.next_chunk)** - 58ms (23%)
3. **streaming_engine.py:268 (FM.next_chunk)** - 48ms (19%)
4. **streaming_engine.py:441 (_waveform)** - 39ms (15%)
5. **granular_layer.py:58 (__init__)** - 50ms (20%)

**Observations:**
- Each layer contributes roughly linear overhead
- Master compression overhead eliminated
- Multi-layer is now 2.3x faster

---

## Remaining Optimization Opportunities

### 🔥 High Impact (Not Yet Implemented)

1. **Subtractive Wavetable Synthesis** — 15-20% potential gain
   - Replace per-sample PolyBLEP with wavetable lookup
   - Pre-compute band-limited waveforms
   - Would reduce subtractive CPU by ~25%

2. **Granular Sample Caching** — Faster initialization
   - Cache resampled samples across renders
   - Lazy-load samples
   - Would eliminate 51% of gran init time

3. **Numba JIT Compilation** — 10-30% potential gain
   - JIT-compile envelope follower (if re-enabled)
   - JIT-compile waveform generation
   - JIT-compile grain spawning logic

### ✅ Completed Optimizations

1. **Master Compression Pre-Computation** ✅
   - Pre-compute compression parameters once
   - Inline compression logic in process()
   - **Result: 2-3x faster rendering**

---

## Recommendations (Priority Order)

### 1. ✅ **Master Compression Optimization** (COMPLETED)
   - **Result**: 2-3x faster rendering across all modes
   - **Status**: All tests pass, no quality degradation

### 2. **Profile Long Renders (30s+)** (Next)
   - **Why**: Verify scaling behavior for segmented rendering
   - **How**: Run profiler with 30s-60s durations
   - **Expected**: Linear scaling, no memory leaks

### 3. **Implement Wavetable Synthesis for Subtractive** (Future)
   - **Why**: Waveform generation is 37% of subtractive CPU
   - **How**: Pre-compute band-limited wavetables
   - **Expected Gain**: 15-20% speedup for subtractive

### 4. **Granular Sample Caching** (Future)
   - **Why**: Sample loading is 51% of granular init
   - **How**: Cache resampled samples in memory
   - **Expected Gain**: Faster initialization

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

## Performance Metrics (For Future Comparison)

**Hardware**: Windows, 12 CPU cores  
**Python**: 3.x  
**NumPy**: Latest  

### Before Optimization (Baseline)

| Mode   | 6s Render Time | Realtime Factor |
|--------|----------------|-----------------|
| FM     | 0.271s         | 22.17x          |
| Sub    | 0.311s         | 19.30x          |
| Gran   | 0.275s         | 21.83x          |
| Multi  | 0.580s         | 10.35x          |

### After Optimization (Current)

| Mode   | 6s Render Time | Realtime Factor | Improvement |
|--------|----------------|-----------------|-------------|
| FM     | 0.080s         | 75.17x          | +239%       |
| Sub    | 0.115s         | 51.98x          | +170%       |
| Gran   | 0.102s         | 59.09x          | +170%       |
| Multi  | 0.252s         | 23.80x          | +130%       |

**Target Met**: ✅ All modes exceed target (>10x multi-layer, >15x single-layer)
