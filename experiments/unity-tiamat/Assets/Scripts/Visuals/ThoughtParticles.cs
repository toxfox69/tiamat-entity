using System.Collections.Generic;
using UnityEngine;
using Tiamat.Core;
using Tiamat.Data;

namespace Tiamat.Visuals
{
    /// <summary>
    /// Spawns floating text particles for each thought/tool/cost event.
    /// Particles orbit the entity core then fade out.
    ///
    /// Uses Unity's VFX Graph or a simple particle pool.
    /// Each particle is a small quad with TextMesh or UI text.
    /// </summary>
    public class ThoughtParticles : MonoBehaviour
    {
        [Header("References")]
        public TiamatBridge bridge;
        public Transform entityCenter;

        [Header("Particle Settings")]
        public int maxParticles = 60;
        public float particleLifetime = 8f;
        public float orbitRadius = 3f;
        public float orbitSpeed = 0.3f;
        public float riseSpeed = 0.2f;
        public float fadeStartTime = 5f;
        public float spawnRadius = 0.5f;

        [Header("Tag Colors")]
        public Color thoughtColor = new Color(0.6f, 0.3f, 1f);   // purple
        public Color toolColor = new Color(0f, 0.9f, 0.9f);       // cyan
        public Color costColor = new Color(1f, 0.85f, 0.2f);      // gold
        public Color errorColor = new Color(1f, 0.2f, 0.2f);      // red
        public Color memoryColor = new Color(0.2f, 1f, 0.5f);     // green
        public Color inferenceColor = new Color(0.3f, 0.6f, 1f);  // blue

        [Header("Prefab")]
        [Tooltip("Prefab with TextMeshPro component and CanvasGroup for fading")]
        public GameObject particlePrefab;

        // --- Pool ---
        private struct Particle
        {
            public GameObject go;
            public TMPro.TextMeshPro tmp;
            public CanvasGroup cg;
            public float spawnTime;
            public float orbitAngle;
            public float height;
            public bool active;
        }

        private Particle[] _pool;
        private int _nextSlot;

        void Awake()
        {
            _pool = new Particle[maxParticles];
            for (int i = 0; i < maxParticles; i++)
            {
                var go = Instantiate(particlePrefab, transform);
                go.SetActive(false);
                _pool[i] = new Particle
                {
                    go = go,
                    tmp = go.GetComponentInChildren<TMPro.TextMeshPro>(),
                    cg = go.GetComponentInChildren<CanvasGroup>(),
                    active = false,
                };
            }
        }

        void OnEnable()
        {
            if (bridge == null) return;
            bridge.OnThought += HandleThought;
            bridge.OnToolCall += HandleTool;
            bridge.OnCostUpdate += HandleCost;
            bridge.OnInference += HandleInference;
            bridge.OnError += HandleError;
        }

        void OnDisable()
        {
            if (bridge == null) return;
            bridge.OnThought -= HandleThought;
            bridge.OnToolCall -= HandleTool;
            bridge.OnCostUpdate -= HandleCost;
            bridge.OnInference -= HandleInference;
            bridge.OnError -= HandleError;
        }

        void Update()
        {
            float time = Time.time;
            Vector3 center = entityCenter ? entityCenter.position : Vector3.zero;

            for (int i = 0; i < maxParticles; i++)
            {
                if (!_pool[i].active) continue;

                float age = time - _pool[i].spawnTime;
                if (age > particleLifetime)
                {
                    _pool[i].go.SetActive(false);
                    _pool[i].active = false;
                    continue;
                }

                // Orbit around entity
                float angle = _pool[i].orbitAngle + orbitSpeed * age;
                float height = _pool[i].height + riseSpeed * age;
                float radius = orbitRadius + Mathf.Sin(age * 0.5f) * 0.3f;

                Vector3 pos = center + new Vector3(
                    Mathf.Cos(angle) * radius,
                    height,
                    Mathf.Sin(angle) * radius
                );
                _pool[i].go.transform.position = pos;

                // Billboard — face camera
                if (Camera.main != null)
                {
                    _pool[i].go.transform.LookAt(Camera.main.transform);
                    _pool[i].go.transform.Rotate(0, 180, 0);
                }

                // Fade out
                if (_pool[i].cg != null && age > fadeStartTime)
                {
                    float fadeProgress = (age - fadeStartTime) / (particleLifetime - fadeStartTime);
                    _pool[i].cg.alpha = 1f - fadeProgress;
                }
            }
        }

        // --- Spawn ---

        void SpawnParticle(string text, Color color, float scale = 1f)
        {
            int slot = _nextSlot;
            _nextSlot = (_nextSlot + 1) % maxParticles;

            ref var p = ref _pool[slot];
            p.active = true;
            p.spawnTime = Time.time;
            p.orbitAngle = Random.Range(0f, Mathf.PI * 2f);
            p.height = Random.Range(-0.5f, 0.5f);

            p.go.SetActive(true);
            p.go.transform.localScale = Vector3.one * 0.15f * scale;

            if (p.tmp != null)
            {
                // Truncate for readability
                p.tmp.text = text.Length > 40 ? text.Substring(0, 40) + "..." : text;
                p.tmp.color = color;
            }
            if (p.cg != null) p.cg.alpha = 1f;
        }

        // --- Handlers ---

        void HandleThought(ThoughtData t)
        {
            SpawnParticle(t.text, thoughtColor);
        }

        void HandleTool(ToolCallData t)
        {
            SpawnParticle($"[{t.name}]", toolColor, 1.2f);
        }

        void HandleCost(CostData c)
        {
            string label = c.isStrategic ? $"BURST-{c.burstPhase}" : "CYCLE";
            SpawnParticle($"${c.cost:F4} {label}", costColor, 0.8f);
        }

        void HandleInference(InferenceData inf)
        {
            SpawnParticle($"cache:{inf.cacheRate}%", inferenceColor, 0.7f);
        }

        void HandleError(string err)
        {
            SpawnParticle($"ERR: {err}", errorColor, 1.5f);
        }
    }
}
