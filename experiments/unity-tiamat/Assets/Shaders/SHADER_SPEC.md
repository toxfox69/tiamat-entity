# TiamatEntity Shader — Shader Graph Specification

URP Shader Graph. Attach to the core entity mesh (icosphere, 3-4 subdivisions).

## Inputs (exposed properties, driven by EntityCore.cs)

| Property | Type | Default | Driven By |
|----------|------|---------|-----------|
| _EmissionColor | Color HDR | (0.3, 0.2, 0.8, 1) | Strategic phase color |
| _EmissionIntensity | Float [0-10] | 1.5 | Cost/burst state |
| _PulseSpeed | Float [0-5] | 0.8 | Cycle frequency |
| _DisplacementStrength | Float [0-0.5] | 0.05 | Token throughput |
| _NoiseScale | Float [0.5-5] | 2.0 | Cache efficiency (inv) |

## Vertex Stage — Displacement

```
// Vertex position offset along normal
float3 noise = GradientNoise(position.xz * _NoiseScale + _Time.y * 0.3);
float pulse = sin(_Time.y * _PulseSpeed) * 0.5 + 0.5;
float displacement = noise * _DisplacementStrength * pulse;
position += normal * displacement;
```

This makes the entity's surface breathe — low displacement during routine,
aggressive deformation during burst cycles.

## Fragment Stage — Emission

```
// Base: dark with emission glow from within
float3 baseColor = float3(0.02, 0.01, 0.03);
float fresnel = pow(1.0 - saturate(dot(viewDir, normal)), 3.0);

// Core glow — brightest at edges (fresnel rim)
float3 emission = _EmissionColor.rgb * _EmissionIntensity * (0.3 + fresnel * 0.7);

// Inner pulse pattern — voronoi cells that shift with time
float voronoi = VoronoiNoise(uv * 4.0 + _Time.y * _PulseSpeed * 0.2);
emission += _EmissionColor.rgb * voronoi * 0.3 * _EmissionIntensity;

// Output
albedo = baseColor;
emissionOut = emission;
alpha = 0.85 + fresnel * 0.15; // Slightly transparent core, solid edges
```

## Strategic Burst Transitions

### Phase 1 — REFLECT (purple)
- Displacement increases inward (negative displacement contribution)
- Voronoi cells contract (scale * 1.5)
- Add spiral UV distortion: `uv += float2(cos(angle), sin(angle)) * 0.1 * pulse`

### Phase 2 — BUILD (green)
- Displacement pushes outward aggressively
- Add crystalline faceting: quantize normals to nearest 12 directions
- Voronoi cells become sharp (step function on distance)
- Emission ramps to max

### Phase 3 — MARKET (gold)
- Add concentric ring emission: `rings = sin(distance(uv, 0.5) * 20 - _Time.y * 3) * 0.5 + 0.5`
- Rings expand outward from center
- High fresnel rim = broadcast aura
- Spawn additional ring particles from EntityCore (trigger in C#)

## Night Mode
- All emission * 0.3
- PulseSpeed * 0.3
- Add subtle star-field dots in the background

## Error Flash
- Driven from C# (EntityCore._errorFlashTimer)
- Lerp emission toward red (1, 0.1, 0.1) at 8Hz ping-pong
- Add screen-space chromatic aberration post-process (optional)

## Cache Shield (separate material on outer sphere)
- Simple transparent unlit shader
- Color: (0.3, 0.6, 1.0, alpha) where alpha = cache_rate / 100 * 0.25
- Fresnel rim only — invisible center, visible edges
- Gentle rotation: UV += _Time.y * 0.05

## Performance Notes
- Target: 90fps on Quest 3 (mobile GPU)
- Use half precision where possible
- Voronoi can be approximated with a 3-octave noise lookup
- Max 2 texture samples (noise LUT + voronoi LUT)
- Single-pass instanced rendering for VR stereo
