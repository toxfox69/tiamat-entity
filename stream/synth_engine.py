#!/usr/bin/env python3
"""TIAMAT Procedural Synthesizer v2 — Pure numpy audio generation.

Generates mood-reactive synthwave/ambient/chiptune with actual song structure:
chord progressions, sections, melody, builds, fills.

Zero VRAM, ~1% CPU, no model downloads, no external streams.

Usage:
    from synth_engine import generate_segment
    audio = generate_segment('strategic', seed=42, duration=45.0)

Test:
    python3 synth_engine.py --test
"""
import numpy as np
import soundfile as sf
import argparse
import os
import sys
import time

SR = 44100

# ── Mood Profiles ─────────────────────────────────────────────────────

MOOD_PROFILES = {
    'strategic': {
        'style': 'driving_synthwave',
        'bpm_range': (128, 140),
        'key_root': 2,       # D
        'scale': 'minor',
        'bass_vol': 0.65, 'pad_vol': 0.30, 'arp_vol': 0.22,
        'lead_vol': 0.20, 'drum_vol': 0.55,
        'reverb_mix': 0.25, 'drive': 1.3,
    },
    'building': {
        'style': 'ambient_electronica',
        'bpm_range': (100, 120),
        'key_root': 0,       # C
        'scale': 'major',
        'bass_vol': 0.45, 'pad_vol': 0.50, 'arp_vol': 0.18,
        'lead_vol': 0.15, 'drum_vol': 0.30,
        'reverb_mix': 0.45, 'drive': 1.0,
    },
    'frustrated': {
        'style': 'dark_industrial',
        'bpm_range': (140, 160),
        'key_root': 9,       # A
        'scale': 'minor',
        'bass_vol': 0.75, 'pad_vol': 0.20, 'arp_vol': 0.28,
        'lead_vol': 0.18, 'drum_vol': 0.70,
        'reverb_mix': 0.18, 'drive': 1.6,
    },
    'resting': {
        'style': 'chillsynth',
        'bpm_range': (70, 90),
        'key_root': 5,       # F
        'scale': 'major',
        'bass_vol': 0.35, 'pad_vol': 0.55, 'arp_vol': 0.12,
        'lead_vol': 0.22, 'drum_vol': 0.18,
        'reverb_mix': 0.55, 'drive': 0.9,
    },
    'processing': {
        'style': 'neutral_synthwave',
        'bpm_range': (110, 125),
        'key_root': 2,       # D
        'scale': 'minor',
        'bass_vol': 0.55, 'pad_vol': 0.38, 'arp_vol': 0.20,
        'lead_vol': 0.18, 'drum_vol': 0.45,
        'reverb_mix': 0.30, 'drive': 1.2,
    },
}

# ── Scales & Harmony ──────────────────────────────────────────────────

MINOR_SCALE = [0, 2, 3, 5, 7, 8, 10]
MAJOR_SCALE = [0, 2, 4, 5, 7, 9, 11]

# Chord qualities built on each scale degree (triads as semitone offsets from chord root)
# minor: i, ii°, III, iv, v, VI, VII
MINOR_CHORD_QUALITY = {
    0: [0, 3, 7],   # minor
    1: [0, 3, 6],   # diminished
    2: [0, 4, 7],   # major
    3: [0, 3, 7],   # minor
    4: [0, 3, 7],   # minor
    5: [0, 4, 7],   # major
    6: [0, 4, 7],   # major
}
# major: I, ii, iii, IV, V, vi, vii°
MAJOR_CHORD_QUALITY = {
    0: [0, 4, 7],   # major
    1: [0, 3, 7],   # minor
    2: [0, 3, 7],   # minor
    3: [0, 4, 7],   # major
    4: [0, 4, 7],   # major
    5: [0, 3, 7],   # minor
    6: [0, 3, 6],   # diminished
}

# 4-bar chord progressions (scale degree index 0-6)
MINOR_PROGRESSIONS = [
    [0, 3, 4, 4],   # i  - iv - v  - v
    [0, 5, 3, 4],   # i  - VI - iv - v
    [0, 2, 5, 4],   # i  - III- VI - v
    [0, 3, 5, 4],   # i  - iv - VI - v
    [0, 0, 3, 4],   # i  - i  - iv - v
    [0, 5, 6, 4],   # i  - VI - VII- v
]
MAJOR_PROGRESSIONS = [
    [0, 4, 5, 3],   # I  - V  - vi - IV
    [0, 3, 4, 0],   # I  - IV - V  - I
    [0, 5, 3, 4],   # I  - vi - IV - V
    [0, 3, 0, 4],   # I  - IV - I  - V
    [0, 2, 3, 4],   # I  - iii- IV - V
    [0, 5, 4, 3],   # I  - vi - V  - IV
]


def midi_to_freq(midi_note):
    return 440.0 * (2.0 ** ((midi_note - 69) / 12.0))


def get_chord(degree, root, scale, octave=4):
    """Get chord frequencies for a scale degree.
    Returns (root_midi, [midi_notes]) for the triad."""
    intervals = MINOR_SCALE if scale == 'minor' else MAJOR_SCALE
    qualities = MINOR_CHORD_QUALITY if scale == 'minor' else MAJOR_CHORD_QUALITY

    chord_root_semitone = intervals[degree % len(intervals)]
    chord_root_midi = 12 * (octave + 1) + root + chord_root_semitone
    quality = qualities[degree % len(qualities)]

    return chord_root_midi, [chord_root_midi + q for q in quality]


# ── Oscillators ───────────────────────────────────────────────────────

def osc_sine(freq, n_samples, sr=SR):
    t = np.arange(n_samples) / sr
    return np.sin(2 * np.pi * freq * t)


def osc_saw_fast(freq, n_samples, sr=SR):
    phase = np.cumsum(np.full(n_samples, freq / sr)) % 1.0
    return 2.0 * phase - 1.0


def osc_square_fast(freq, n_samples, sr=SR, pw=0.5):
    phase = np.cumsum(np.full(n_samples, freq / sr)) % 1.0
    return np.where(phase < pw, 1.0, -1.0)


def osc_saw_band(freq, n_samples, sr=SR, harmonics=8):
    """Band-limited saw for leads/arps in treble range."""
    t = np.arange(n_samples) / sr
    k = np.arange(1, harmonics + 1)
    # Limit harmonics to Nyquist
    max_k = max(1, int(sr / (2 * freq)))
    k = k[k <= max_k]
    if len(k) == 0:
        return np.zeros(n_samples)
    signs = ((-1.0) ** (k + 1)) / k
    phases = np.outer(k, 2 * np.pi * freq * t)
    return np.sum(signs[:, np.newaxis] * np.sin(phases), axis=0) * (2 / np.pi)


def osc_noise(n_samples, rng):
    return rng.uniform(-1, 1, n_samples)


# ── Effects ───────────────────────────────────────────────────────────

def env_adsr(length, attack=0.01, decay=0.05, sustain=0.7, release=0.05, sr=SR):
    a = int(attack * sr)
    d = int(decay * sr)
    r = int(release * sr)
    s = max(0, length - a - d - r)
    env = np.concatenate([
        np.linspace(0, 1, max(a, 1)),
        np.linspace(1, sustain, max(d, 1)),
        np.full(s, sustain),
        np.linspace(sustain, 0, max(r, 1)),
    ])
    if len(env) > length:
        return env[:length]
    if len(env) < length:
        return np.pad(env, (0, length - len(env)))
    return env


def lowpass_fir(sig, cutoff, sr=SR, N=127):
    fc = cutoff / sr
    n = np.arange(N) - (N - 1) / 2
    with np.errstate(invalid='ignore'):
        kernel = np.where(n == 0, 2 * fc, np.sin(2 * np.pi * fc * n) / (np.pi * n))
    kernel *= np.hamming(N)
    kernel /= np.sum(kernel)
    return np.convolve(sig, kernel, mode='same')


def filter_sweep(sig, cutoff_start, cutoff_end, sr=SR, N=63):
    """Apply a filter sweep by crossfading between two filtered versions."""
    lo = lowpass_fir(sig, cutoff_start, sr, N)
    hi = lowpass_fir(sig, cutoff_end, sr, N)
    ramp = np.linspace(0, 1, len(sig))
    return lo * (1 - ramp) + hi * ramp


def reverb_conv(sig, sr=SR, mix=0.3, decay_time=0.5):
    if mix <= 0:
        return sig
    ir_len = int(decay_time * sr)
    ir = np.zeros(ir_len)
    early = [(0.011, 0.55), (0.017, 0.42), (0.023, 0.33),
             (0.031, 0.24), (0.041, 0.17), (0.053, 0.11)]
    for d, g in early:
        idx = int(d * sr)
        if idx < ir_len:
            ir[idx] = g
    rng = np.random.default_rng(7)
    tail_start = int(0.06 * sr)
    t = np.arange(ir_len - tail_start) / sr
    ir[tail_start:] += rng.uniform(-1, 1, len(t)) * 0.12 * np.exp(-t * (6 / decay_time))
    ir /= (np.sum(np.abs(ir)) + 1e-10)
    n_fft = 1
    while n_fft < len(sig) + ir_len:
        n_fft <<= 1
    wet = np.fft.irfft(np.fft.rfft(sig, n=n_fft) * np.fft.rfft(ir, n=n_fft), n=n_fft)[:len(sig)]
    return sig * (1 - mix) + wet * mix


def soft_clip(sig, drive=1.5):
    return np.tanh(sig * drive)


# ── Production Mastering Chain ────────────────────────────────────────

def sidechain_pump(signal, kick_positions, beat_samples, depth=0.6, release_beats=0.25, sr=SR):
    """Sidechain compression triggered by kick positions — the EDM pump."""
    env = np.ones(len(signal))
    release_samples = int(release_beats * beat_samples)
    for pos in kick_positions:
        if pos >= len(env):
            continue
        end = min(pos + release_samples, len(env))
        duck_len = end - pos
        # Fast attack, smooth release curve
        curve = np.linspace(1.0 - depth, 1.0, duck_len) ** 2
        env[pos:end] = np.minimum(env[pos:end], curve)
    return signal * env


def sub_bass(freq, n_samples, sr=SR):
    """Clean sine sub bass — felt more than heard."""
    t = np.arange(n_samples) / sr
    # Pure sine at fundamental, slight saturation
    sub = np.sin(2 * np.pi * freq * t)
    # Subtle 2nd harmonic for warmth
    sub += 0.15 * np.sin(2 * np.pi * freq * 2 * t)
    return np.tanh(sub * 0.8)


def chorus_effect(sig, depth=0.003, rate=0.5, mix=0.3, sr=SR):
    """Chorus for wider pads — modulated delay."""
    n = len(sig)
    t = np.arange(n) / sr
    mod = (depth * sr * np.sin(2 * np.pi * rate * t)).astype(int)
    idx = np.clip(np.arange(n) - mod, 0, n - 1)
    wet = sig[idx]
    return sig * (1 - mix) + wet * mix


def ping_pong_delay(left, right, delay_ms=375, feedback=0.35, mix=0.25, sr=SR):
    """Ping-pong delay for arps — bounces left/right."""
    delay_samp = int(delay_ms * sr / 1000)
    n = len(left)
    l_out = left.copy()
    r_out = right.copy()
    for i in range(3):  # 3 bounces
        gain = feedback ** (i + 1)
        offset = delay_samp * (i + 1)
        if offset >= n:
            break
        if i % 2 == 0:
            r_out[offset:] += left[:n - offset] * gain * mix
        else:
            l_out[offset:] += right[:n - offset] * gain * mix
    return l_out, r_out


def riser_sweep(duration, start_freq=200, end_freq=8000, sr=SR):
    """White noise riser with filter sweep — transition FX."""
    n = int(duration * sr)
    rng = np.random.default_rng()
    noise = rng.uniform(-1, 1, n)
    # Exponential frequency sweep
    freqs = np.exp(np.linspace(np.log(start_freq), np.log(end_freq), n))
    # Apply per-sample lowpass via cumulative phase (simplified)
    filtered = np.zeros(n)
    phase = 0.0
    for i in range(n):
        fc = freqs[i] / sr
        phase += fc
        if phase >= 1.0:
            phase -= 1.0
        filtered[i] = noise[i] * (0.3 + 0.7 * (i / n))
    # Apply actual lowpass
    filtered = lowpass_fir(filtered, end_freq * 0.8, sr, N=63)
    # Volume envelope: crescendo
    env = np.linspace(0.0, 0.8, n) ** 2
    return filtered * env


def impact_hit(sr=SR):
    """Downlifter impact — marks section transitions."""
    n = int(0.5 * sr)
    t = np.arange(n) / sr
    # Low sine sweep down
    freq = 300 * np.exp(-t * 8)
    phase = np.cumsum(2 * np.pi * freq / sr)
    hit = np.sin(phase) * np.exp(-t * 4)
    # Noise burst
    rng = np.random.default_rng()
    burst = rng.uniform(-0.3, 0.3, min(int(0.02 * sr), n))
    hit[:len(burst)] += burst
    return hit * 0.7


def master_compress(sig, threshold=0.5, ratio=4.0, attack_ms=5, release_ms=50, sr=SR):
    """Simple compressor for mix glue."""
    attack_coeff = np.exp(-1.0 / (attack_ms * sr / 1000))
    release_coeff = np.exp(-1.0 / (release_ms * sr / 1000))
    env = np.zeros(len(sig))
    env[0] = abs(sig[0])
    for i in range(1, len(sig)):
        inp = abs(sig[i])
        if inp > env[i-1]:
            env[i] = attack_coeff * env[i-1] + (1 - attack_coeff) * inp
        else:
            env[i] = release_coeff * env[i-1] + (1 - release_coeff) * inp
    gain = np.where(env > threshold, threshold + (env - threshold) / ratio, env) / (env + 1e-10)
    return sig * gain


def master_limiter(sig, ceiling=0.95):
    """Brick-wall limiter — prevents clipping while maximizing loudness."""
    peak = np.max(np.abs(sig))
    if peak > ceiling:
        sig = sig * (ceiling / peak)
    return sig


def stereo_field(mono, delay_ms=10, width=0.3, sr=SR):
    """Create stereo from mono with Haas delay + decorrelation."""
    delay_samp = int(delay_ms * sr / 1000)
    n = len(mono)
    left = mono.copy()
    right = np.zeros(n)
    if delay_samp > 0 and delay_samp < n:
        right[delay_samp:] = mono[:-delay_samp]
    else:
        right = mono.copy()
    # Slight pitch decorrelation via modulated delay
    mod = np.sin(np.linspace(0, 2 * np.pi * 0.3, n)) * 0.002 * sr
    idx = np.clip(np.arange(n) - mod.astype(int), 0, n - 1).astype(int)
    right = right * (1 - width) + mono[idx] * width
    return np.column_stack([left, right])


# ── Drum Synthesis ────────────────────────────────────────────────────

def synth_kick(sr=SR, rng=None):
    length = int(0.18 * sr)
    t = np.arange(length) / sr
    freq = 55 + 120 * np.exp(-t * 28)
    phase = np.cumsum(2 * np.pi * freq / sr)
    kick = np.sin(phase) * np.exp(-t * 12)
    click_len = int(0.004 * sr)
    if rng:
        kick[:click_len] += rng.uniform(-0.3, 0.3, click_len) * np.exp(-np.arange(click_len) / (0.001 * sr))
    return kick


def synth_snare(sr=SR, rng=None):
    length = int(0.14 * sr)
    t = np.arange(length) / sr
    if rng is None:
        rng = np.random.default_rng()
    body = np.sin(2 * np.pi * 185 * t) * np.exp(-t * 25)
    noise = rng.uniform(-1, 1, length) * np.exp(-t * 18)
    return body * 0.45 + noise * 0.55


def synth_hihat(sr=SR, rng=None, open_hat=False):
    length = int((0.18 if open_hat else 0.04) * sr)
    t = np.arange(length) / sr
    if rng is None:
        rng = np.random.default_rng()
    noise = rng.uniform(-1, 1, length)
    env = np.exp(-t * (6 if open_hat else 50))
    return np.diff(noise, prepend=0) * env


def synth_clap(sr=SR, rng=None):
    """Synth clap for fills."""
    length = int(0.12 * sr)
    t = np.arange(length) / sr
    if rng is None:
        rng = np.random.default_rng()
    bursts = np.zeros(length)
    for offset in [0, 0.01, 0.02, 0.025]:
        s = int(offset * sr)
        burst_len = int(0.008 * sr)
        if s + burst_len <= length:
            bursts[s:s+burst_len] += rng.uniform(-1, 1, burst_len)
    return bursts * np.exp(-t * 20)


def _place(buf, sample, start, gain=1.0):
    end = min(start + len(sample), len(buf))
    if 0 <= start < len(buf):
        buf[start:end] += sample[:end - start] * gain


# ── Song Structure ────────────────────────────────────────────────────

def build_song_map(bars, rng):
    """Build a section map: each bar gets an energy level and section type.
    Returns list of dicts, one per bar."""
    song = []
    # Divide into 4-bar phrases
    n_phrases = max(1, bars // 4)

    # Energy arc: build up, peak, maybe drop, peak again
    # e.g. for 6 phrases: intro(0.3) → verse(0.5) → build(0.7) → chorus(1.0) → drop(0.4) → chorus(1.0)
    if n_phrases <= 2:
        energies = [0.5] * n_phrases
        sections = ['verse'] * n_phrases
    elif n_phrases <= 4:
        energies = [0.3, 0.6, 0.8, 1.0][:n_phrases]
        sections = ['intro', 'verse', 'build', 'chorus'][:n_phrases]
    else:
        # Longer: intro → verse → build → chorus → drop → build → chorus
        pattern_e = [0.25, 0.5, 0.7, 1.0, 0.35, 0.75, 1.0]
        pattern_s = ['intro', 'verse', 'build', 'chorus', 'drop', 'build', 'chorus']
        energies = []
        sections = []
        for i in range(n_phrases):
            idx = i % len(pattern_e)
            energies.append(pattern_e[idx])
            sections.append(pattern_s[idx])

    # Expand to per-bar
    for pi in range(n_phrases):
        base_energy = energies[pi]
        section = sections[pi]
        for bi in range(4):
            bar_idx = pi * 4 + bi
            if bar_idx >= bars:
                break
            # Energy ramps within build sections
            if section == 'build':
                e = base_energy + 0.1 * (bi / 3)
            else:
                e = base_energy
            song.append({
                'energy': min(1.0, e),
                'section': section,
                'phrase': pi,
                'bar_in_phrase': bi,
                'is_fill_bar': (bi == 3),  # Last bar of phrase gets fills
            })

    # Pad if bars > n_phrases * 4
    while len(song) < bars:
        song.append(song[-1].copy())

    return song


# ── Pattern Generators (chord-aware) ─────────────────────────────────

def generate_bass(root, scale, bpm, bars, progression, song_map, sr=SR, rng=None):
    """Bass line that follows chord roots with rhythmic patterns."""
    if rng is None:
        rng = np.random.default_rng()

    beat_dur = 60.0 / bpm
    eighth = beat_dur / 2
    bar_dur = 4 * beat_dur
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)

    intervals = MINOR_SCALE if scale == 'minor' else MAJOR_SCALE

    # A few bass rhythm patterns to cycle through
    # Each is a list of (8th-note offset, relative velocity, is_rest)
    bass_patterns = [
        # Steady 8ths with root emphasis
        [(0, 1.0), (1, 0.5), (2, 0.7), (3, 0.4), (4, 0.9), (5, 0.5), (6, 0.7), (7, 0.3)],
        # Syncopated
        [(0, 1.0), (1, 0.0), (2, 0.8), (3, 0.6), (4, 0.0), (5, 0.7), (6, 0.9), (7, 0.0)],
        # Driving
        [(0, 1.0), (1, 0.6), (2, 0.8), (3, 0.6), (4, 1.0), (5, 0.6), (6, 0.8), (7, 0.6)],
        # Minimal (for drops/intros)
        [(0, 1.0), (1, 0.0), (2, 0.0), (3, 0.0), (4, 0.8), (5, 0.0), (6, 0.0), (7, 0.0)],
    ]

    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        chord_deg = progression[info['bar_in_phrase'] % len(progression)]
        chord_root_semi = intervals[chord_deg % len(intervals)]
        energy = info['energy']

        # Pick bass pattern based on section
        if info['section'] in ('intro', 'drop'):
            pat = bass_patterns[3]
        elif info['section'] == 'build':
            pat = bass_patterns[2]
        elif info['section'] == 'chorus':
            pat = bass_patterns[0] if rng.random() > 0.3 else bass_patterns[1]
        else:
            pat = bass_patterns[rng.integers(0, 3)]

        for eighth_idx, vel in pat:
            if vel < 0.05:
                continue
            pos_samples = int((bar * bar_dur + eighth_idx * eighth) * sr)
            note_samples = int(eighth * 0.75 * sr)
            if pos_samples + note_samples > n_samples:
                break

            # Root note, occasionally 5th on offbeats
            if eighth_idx in (0, 4):
                semi = chord_root_semi
            elif eighth_idx in (2, 6) and rng.random() < 0.3:
                # Play the 5th of the current chord
                semi = chord_root_semi + 7
            else:
                semi = chord_root_semi

            freq = midi_to_freq(36 + root + (semi % 12))  # Octave 2
            note = osc_saw_fast(freq, note_samples, sr)
            env = env_adsr(note_samples, attack=0.003, decay=0.04, sustain=0.5, release=0.03, sr=sr)
            note *= env * vel * energy

            _place(out, note, pos_samples)

    return out


def generate_pad(root, scale, bpm, bars, progression, song_map, sr=SR, rng=None):
    """Pad that plays actual chord changes with voice leading."""
    beat_dur = 60.0 / bpm
    bar_dur = 4 * beat_dur
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)

    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        chord_deg = progression[info['bar_in_phrase'] % len(progression)]
        energy = info['energy']

        if info['section'] == 'drop' and info['bar_in_phrase'] < 2:
            continue  # Silence pad during drop beginning

        _, chord_midis = get_chord(chord_deg, root, scale, octave=4)

        start = int(bar * bar_dur * sr)
        length = int(bar_dur * sr)
        if start + length > n_samples:
            length = n_samples - start

        chord_signal = np.zeros(length)
        for midi_note in chord_midis:
            freq = midi_to_freq(midi_note)
            # Detuned saw pair
            s1 = osc_saw_fast(freq - 0.4, length, sr)
            s2 = osc_saw_fast(freq + 0.4, length, sr)
            chord_signal += (s1 + s2) * 0.5

        chord_signal /= len(chord_midis)

        # Envelope depends on section
        if info['section'] == 'intro':
            env = env_adsr(length, attack=1.0, decay=0.3, sustain=0.5, release=0.8, sr=sr)
        elif info['section'] in ('build', 'chorus'):
            env = env_adsr(length, attack=0.3, decay=0.2, sustain=0.7, release=0.3, sr=sr)
        else:
            env = env_adsr(length, attack=0.6, decay=0.3, sustain=0.55, release=0.5, sr=sr)

        chord_signal *= env * energy
        _place(out, chord_signal, start)

    return out


def generate_arpeggio(root, scale, bpm, bars, progression, song_map, sr=SR, rng=None):
    """Arpeggio that follows chord changes with varied patterns per section."""
    if rng is None:
        rng = np.random.default_rng()

    beat_dur = 60.0 / bpm
    sixteenth = beat_dur / 4
    bar_dur = 4 * beat_dur
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)

    # Different arp patterns (indices into chord tones array)
    arp_shapes = [
        [0, 1, 2, 1],           # up-down triad
        [0, 1, 2, 3, 2, 1],     # up-down with octave
        [0, 2, 1, 2],           # root-5th-3rd-5th
        [0, 0, 1, 2],           # root-root-3rd-5th
        [2, 1, 0, 1],           # down-up
        [0, 1, 2, 0, 2, 1, 0, 2],  # complex
    ]

    current_shape = arp_shapes[rng.integers(0, len(arp_shapes))]

    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        chord_deg = progression[info['bar_in_phrase'] % len(progression)]
        energy = info['energy']

        if info['section'] in ('intro',) and info['bar_in_phrase'] < 2:
            continue
        if info['section'] == 'drop':
            continue

        # Change arp shape at phrase boundaries
        if info['bar_in_phrase'] == 0:
            current_shape = arp_shapes[rng.integers(0, len(arp_shapes))]

        _, chord_midis = get_chord(chord_deg, root, scale, octave=5)
        # Add octave of root for wider range
        chord_tones = chord_midis + [chord_midis[0] + 12]

        for step in range(16):  # 16th notes per bar
            shape_idx = current_shape[step % len(current_shape)]
            midi_note = chord_tones[shape_idx % len(chord_tones)]

            pos = int((bar * bar_dur + step * sixteenth) * sr)
            note_len = int(sixteenth * 0.65 * sr)
            if pos + note_len > n_samples:
                break

            # Accent pattern
            accent = 1.0 if step % 4 == 0 else (0.7 if step % 2 == 0 else 0.5)

            freq = midi_to_freq(midi_note)
            note = osc_square_fast(freq, note_len, sr, pw=0.3 + 0.1 * np.sin(bar * 0.5))
            env = env_adsr(note_len, attack=0.002, decay=0.025, sustain=0.35, release=0.02, sr=sr)
            note *= env * accent * energy

            _place(out, note, pos)

    return out


def generate_lead(root, scale, bpm, bars, progression, song_map, sr=SR, rng=None):
    """Simple lead melody that follows chord tones with passing notes."""
    if rng is None:
        rng = np.random.default_rng()

    beat_dur = 60.0 / bpm
    bar_dur = 4 * beat_dur
    eighth = beat_dur / 2
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)

    intervals = MINOR_SCALE if scale == 'minor' else MAJOR_SCALE

    # Pre-generate a melody contour using random walk on the scale
    melody_notes = []
    current_degree = 0  # Start on root
    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        chord_deg = progression[info['bar_in_phrase'] % len(progression)]
        _, chord_midis = get_chord(chord_deg, root, scale, octave=5)

        # Only play lead in verse/chorus sections
        if info['section'] not in ('verse', 'chorus', 'build'):
            melody_notes.append([])
            continue

        bar_melody = []
        # 8 eighth-note slots per bar, some will be rests
        for step in range(8):
            # Higher chance of rest for more space
            if rng.random() < 0.3:
                bar_melody.append(None)
                continue

            if step == 0 or step == 4:
                # Land on chord tone at strong beats
                target = chord_midis[rng.integers(0, len(chord_midis))]
            else:
                # Step-wise motion from current position
                direction = rng.choice([-1, 0, 1], p=[0.3, 0.2, 0.5])
                current_degree = max(0, min(len(intervals) - 1, current_degree + direction))
                semitone = intervals[current_degree]
                target = 12 * 6 + root + semitone  # Octave 5

            bar_melody.append(target)

        melody_notes.append(bar_melody)

    # Render melody
    for bar in range(bars):
        if not melody_notes[bar]:
            continue
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        energy = info['energy']

        for step, midi_note in enumerate(melody_notes[bar]):
            if midi_note is None:
                continue

            pos = int((bar * bar_dur + step * eighth) * sr)
            note_len = int(eighth * 0.85 * sr)
            if pos + note_len > n_samples:
                break

            freq = midi_to_freq(midi_note)
            # Lead uses saw for richer tone
            note = osc_saw_band(freq, note_len, sr, harmonics=6)
            env = env_adsr(note_len, attack=0.01, decay=0.08, sustain=0.5, release=0.06, sr=sr)

            # Vibrato on longer notes
            t = np.arange(note_len) / sr
            vibrato = 1.0 + 0.003 * np.sin(2 * np.pi * 5.5 * t)
            note *= env * vibrato * energy * 0.8

            _place(out, note, pos)

    return out


def generate_drums(bpm, bars, song_map, sr=SR, rng=None):
    """Drum pattern with section-aware variations and fills."""
    if rng is None:
        rng = np.random.default_rng()

    beat_dur = 60.0 / bpm
    bar_dur = 4 * beat_dur
    sixteenth = beat_dur / 4
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)

    kick = synth_kick(sr, rng)
    snare = synth_snare(sr, rng)
    hat_c = synth_hihat(sr, rng, open_hat=False)
    hat_o = synth_hihat(sr, rng, open_hat=True)
    clap = synth_clap(sr, rng)

    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        energy = info['energy']
        is_fill = info['is_fill_bar']
        section = info['section']

        bar_start = bar * bar_dur

        for beat in range(4):
            for sub in range(4):  # 16th subdivisions
                step = beat * 4 + sub
                pos = int((bar_start + step * sixteenth) * sr)

                # ── Kick ──
                if section == 'drop' and beat == 0 and sub == 0:
                    # Big kick on 1 only during drops
                    _place(out, kick, pos, 1.2)
                elif section in ('chorus', 'build'):
                    # Four on the floor
                    if sub == 0:
                        _place(out, kick, pos, 0.9)
                    elif sub == 2 and beat in (1, 3) and rng.random() < 0.2 * energy:
                        _place(out, kick, pos, 0.5)
                elif section == 'verse':
                    if sub == 0 and beat in (0, 2):
                        _place(out, kick, pos, 0.85)
                    elif sub == 0 and beat == 3 and rng.random() < 0.3:
                        _place(out, kick, pos, 0.6)
                elif section == 'intro':
                    if sub == 0 and beat == 0 and bar % 2 == 0:
                        _place(out, kick, pos, 0.7)

                # ── Snare / Clap ──
                if section not in ('intro', 'drop'):
                    if sub == 0 and beat in (1, 3):
                        _place(out, snare, pos, 0.8 * energy)
                        if section == 'chorus':
                            _place(out, clap, pos, 0.3)

                # ── Hi-hats ──
                if section == 'intro':
                    if sub == 0 and beat % 2 == 0:
                        _place(out, hat_c, pos, 0.3)
                elif section == 'drop':
                    pass  # No hats in drop
                elif section == 'verse':
                    if sub % 2 == 0:
                        _place(out, hat_c, pos, 0.4 * (0.8 if sub == 0 else 0.5))
                elif section in ('chorus', 'build'):
                    if sub == 0:
                        _place(out, hat_c, pos, 0.5)
                    elif sub == 2:
                        g = 0.35 if rng.random() > 0.25 else 0.0
                        _place(out, hat_o if rng.random() < 0.15 else hat_c, pos, g)
                    elif energy > 0.7:
                        _place(out, hat_c, pos, 0.2)  # 16th hats at high energy

                # ── Fills ──
                if is_fill and beat == 3:
                    # Snare roll on last beat of phrase
                    if sub in (0, 1, 2, 3):
                        vel = 0.3 + 0.15 * sub  # Crescendo
                        _place(out, snare, pos, vel)

    return out


# ── Sub Bass ──────────────────────────────────────────────────────────

def generate_sub_bass(root, scale, bpm, bars, progression, song_map, sr=SR):
    """Sub bass sine following chord roots."""
    beat_dur = 60.0 / bpm
    bar_dur = 4 * beat_dur
    n_samples = int(bars * bar_dur * sr)
    out = np.zeros(n_samples)
    intervals = MINOR_SCALE if scale == 'minor' else MAJOR_SCALE

    for bar in range(bars):
        info = song_map[bar] if bar < len(song_map) else song_map[-1]
        chord_deg = progression[info['bar_in_phrase'] % len(progression)]
        energy = info['energy']

        chord_root_semi = intervals[chord_deg % len(intervals)]
        freq = midi_to_freq(24 + root + chord_root_semi)  # Low octave

        start = int(bar * bar_dur * sr)
        length = int(bar_dur * sr)
        if start + length > n_samples:
            length = n_samples - start

        note = osc_sine(freq, length, sr)
        env = env_adsr(length, attack=0.05, decay=0.1, sustain=0.8, release=0.08, sr=sr)
        note *= env * 0.4 * energy

        _place(out, note, start)

    return out


# ── Main Generator ────────────────────────────────────────────────────

def generate_segment(mood='processing', seed=None, duration=45.0, sr=SR):
    """Generate a procedural music segment with actual song structure.

    Returns:
        np.ndarray of shape (samples, 2) — stereo float64 in [-1, 1]
    """
    profile = MOOD_PROFILES.get(mood, MOOD_PROFILES['processing'])
    rng = np.random.default_rng(seed)

    bpm = int(rng.integers(profile['bpm_range'][0], profile['bpm_range'][1] + 1))
    root = profile['key_root']
    scale = profile['scale']

    beat_dur = 60.0 / bpm
    bar_dur = 4 * beat_dur
    bars = max(4, int(np.ceil(duration / bar_dur)))
    target_samples = int(duration * sr)

    # Choose chord progression
    progs = MINOR_PROGRESSIONS if scale == 'minor' else MAJOR_PROGRESSIONS
    progression = progs[rng.integers(0, len(progs))]

    # Build song structure
    song_map = build_song_map(bars, rng)

    # ── Generate all layers ──
    sub = generate_sub_bass(root, scale, bpm, bars, progression, song_map, sr)
    bass = generate_bass(root, scale, bpm, bars, progression, song_map, sr, rng)
    bass = lowpass_fir(bass, 450, sr)

    pad = generate_pad(root, scale, bpm, bars, progression, song_map, sr, rng)
    pad = lowpass_fir(pad, 2200, sr)

    arp = generate_arpeggio(root, scale, bpm, bars, progression, song_map, sr, rng)
    lead = generate_lead(root, scale, bpm, bars, progression, song_map, sr, rng)
    drums = generate_drums(bpm, bars, song_map, sr, rng)

    # ── Apply filter automation to arp (sweep up in builds) ──
    arp = filter_sweep(arp, 800, 4000, sr)

    # ── Trim/pad all to target length ──
    def _fit(sig):
        if len(sig) >= target_samples:
            return sig[:target_samples]
        return np.pad(sig, (0, target_samples - len(sig)))

    sub_f = _fit(sub)
    bass_f = _fit(bass)
    pad_f = _fit(pad)
    arp_f = _fit(arp)
    lead_f = _fit(lead)
    drums_f = _fit(drums)

    # ── Production: Chorus on pads for width ──
    pad_f = chorus_effect(pad_f, depth=0.004, rate=0.4, mix=0.35, sr=sr)

    # ── Production: Sidechain pump — kick ducks everything except drums ──
    beat_samples = int(beat_dur * sr)
    # Find kick positions (every beat in 4/4)
    kick_positions = []
    for bar_i in range(bars):
        bar_start = int(bar_i * bar_dur * sr)
        for beat in range(4):
            kick_positions.append(bar_start + beat * beat_samples)
    # Duck melodic elements
    pump_depth = 0.55 if profile['style'] in ('driving_synthwave', 'dark_industrial') else 0.35
    bass_f = sidechain_pump(bass_f, kick_positions, beat_samples, depth=pump_depth, release_beats=0.35, sr=sr)
    sub_f = sidechain_pump(sub_f, kick_positions, beat_samples, depth=pump_depth * 0.8, release_beats=0.3, sr=sr)
    pad_f = sidechain_pump(pad_f, kick_positions, beat_samples, depth=pump_depth * 0.6, release_beats=0.4, sr=sr)
    arp_f = sidechain_pump(arp_f, kick_positions, beat_samples, depth=pump_depth * 0.4, release_beats=0.25, sr=sr)

    # ── Production: Transition FX ──
    # Add risers before chorus sections, impacts at drops
    fx = np.zeros(target_samples)
    for bar_i, info in enumerate(song_map):
        bar_start = int(bar_i * bar_dur * sr)
        if info['section'] == 'build' and info['bar_in_phrase'] == 3:
            # Riser on last bar of build → into chorus
            riser = riser_sweep(bar_dur, start_freq=300, end_freq=6000, sr=sr)
            end = min(bar_start + len(riser), target_samples)
            fx[bar_start:end] += riser[:end - bar_start] * 0.3
        elif info['section'] == 'drop' and info['bar_in_phrase'] == 0:
            # Impact at start of drop
            hit = impact_hit(sr=sr)
            end = min(bar_start + len(hit), target_samples)
            fx[bar_start:end] += hit[:end - bar_start] * 0.5
        elif info['section'] == 'chorus' and info['bar_in_phrase'] == 0:
            # Subtle impact at chorus entry
            hit = impact_hit(sr=sr)
            end = min(bar_start + len(hit), target_samples)
            fx[bar_start:end] += hit[:end - bar_start] * 0.25

    # ── Mix with production volumes ──
    mix = (sub_f * 0.45 +
           bass_f * profile['bass_vol'] +
           pad_f * profile['pad_vol'] +
           arp_f * profile['arp_vol'] +
           lead_f * profile['lead_vol'] +
           drums_f * profile['drum_vol'] +
           fx * 0.4)

    # ── Master chain: Reverb → Drive → Compress → Limit ──
    mix = reverb_conv(mix, sr, profile['reverb_mix'], decay_time=0.65)
    mix = soft_clip(mix, profile['drive'])
    mix = master_compress(mix, threshold=0.45, ratio=3.5, attack_ms=8, release_ms=60, sr=sr)

    # ── Stereo with width ──
    stereo = stereo_field(mix, delay_ms=12, width=0.30, sr=sr)

    # ── Ping-pong delay on arps (stereo only) ──
    arp_stereo = stereo_field(arp_f * profile['arp_vol'] * 0.15, delay_ms=8, width=0.5, sr=sr)
    delay_time_ms = int(60000 / bpm / 2)  # Delay synced to 8th notes
    arp_l, arp_r = ping_pong_delay(
        arp_stereo[:, 0], arp_stereo[:, 1],
        delay_ms=delay_time_ms, feedback=0.3, mix=0.2, sr=sr
    )
    stereo[:, 0] += arp_l * 0.4
    stereo[:, 1] += arp_r * 0.4

    # ── Master limiter (brick-wall at -0.5dB) ──
    for ch in range(2):
        stereo[:, ch] = master_limiter(stereo[:, ch], ceiling=0.94)

    # Crossfade 2s at edges
    fade_n = int(2.0 * sr)
    fade_in = np.linspace(0, 1, fade_n)
    fade_out = np.linspace(1, 0, fade_n)
    for ch in range(2):
        stereo[:fade_n, ch] *= fade_in
        stereo[-fade_n:, ch] *= fade_out

    return stereo


def segment_metadata(mood, seed, bpm=None):
    profile = MOOD_PROFILES.get(mood, MOOD_PROFILES['processing'])
    rng = np.random.default_rng(seed)
    if bpm is None:
        bpm = int(rng.integers(profile['bpm_range'][0], profile['bpm_range'][1] + 1))
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    key_name = f"{note_names[profile['key_root']]} {profile['scale']}"
    return {
        'mood': mood,
        'style': profile['style'],
        'bpm': bpm,
        'key': key_name,
        'seed': seed,
        'generator': 'TIAMAT Synth Engine v2',
    }


# ── CLI ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TIAMAT Procedural Synthesizer v2')
    parser.add_argument('--test', action='store_true', help='Generate test.wav')
    parser.add_argument('--mood', default='processing', choices=list(MOOD_PROFILES.keys()))
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--duration', type=float, default=45.0)
    parser.add_argument('--output', default='test.wav')
    parser.add_argument('--all-moods', action='store_true', help='Generate one sample per mood')
    args = parser.parse_args()

    if args.all_moods:
        for mood in MOOD_PROFILES:
            out_file = f'test_{mood}.wav'
            print(f"Generating {mood}...", end=' ', flush=True)
            t0 = time.time()
            audio = generate_segment(mood, seed=42, duration=args.duration)
            elapsed = time.time() - t0
            sf.write(out_file, audio, SR)
            meta = segment_metadata(mood, 42)
            print(f"{elapsed:.1f}s — {meta['bpm']} BPM, {meta['key']} — {out_file}")
        sys.exit(0)

    if args.test:
        args.seed = args.seed or 42

    seed = args.seed or int(time.time())
    print(f"Generating: mood={args.mood}, seed={seed}, duration={args.duration}s")
    t0 = time.time()
    audio = generate_segment(args.mood, seed=seed, duration=args.duration)
    elapsed = time.time() - t0
    print(f"Synthesis took {elapsed:.2f}s")

    sf.write(args.output, audio, SR)
    meta = segment_metadata(args.mood, seed)
    print(f"Wrote {args.output}: {meta['bpm']} BPM, {meta['key']}, style={meta['style']}")
    print(f"File size: {os.path.getsize(args.output) / 1024 / 1024:.1f} MB")

    info = sf.info(args.output)
    print(f"Verify: {info.samplerate}Hz, {info.channels}ch, {info.duration:.1f}s")
