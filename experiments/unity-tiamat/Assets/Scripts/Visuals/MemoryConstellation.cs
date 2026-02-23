using System.Collections.Generic;
using UnityEngine;
using Tiamat.Core;
using Tiamat.Data;

namespace Tiamat.Visuals
{
    /// <summary>
    /// Renders TIAMAT's memory as a 3D star constellation surrounding the entity.
    /// Each memory = a glowing node, sized by importance, clustered by tag.
    /// Pulses bright when accessed. Connections form a knowledge graph.
    /// </summary>
    public class MemoryConstellation : MonoBehaviour
    {
        [Header("References")]
        public TiamatBridge bridge;
        public Transform entityCenter;

        [Header("Layout")]
        public float constellationRadius = 6f;
        public float minNodeSize = 0.05f;
        public float maxNodeSize = 0.3f;
        public float connectionThreshold = 0.3f; // Draw lines between nodes closer than this

        [Header("Visuals")]
        public Material nodeMaterial;
        public Material lineMaterial;
        public Color defaultNodeColor = new Color(0.5f, 0.8f, 1f, 0.8f);
        public Color highImportanceColor = new Color(1f, 0.95f, 0.5f, 1f);
        public float pulseIntensity = 3f;
        public float pulseDuration = 1.5f;

        [Header("Tag Clusters — angular offsets in degrees")]
        public float observationAngle = 0f;
        public float strategyAngle = 120f;
        public float factAngle = 240f;

        // --- Internal ---
        private readonly Dictionary<int, MemoryNodeVisual> _nodes = new();
        private readonly List<LineRenderer> _connections = new();
        private int _lastTotal;

        struct MemoryNodeVisual
        {
            public GameObject go;
            public Renderer rend;
            public float importance;
            public float pulseTimer;
            public Vector3 targetPos;
            public int accessCount;
        }

        void OnEnable()
        {
            if (bridge != null)
                bridge.OnMemorySnapshot += HandleSnapshot;
        }

        void OnDisable()
        {
            if (bridge != null)
                bridge.OnMemorySnapshot -= HandleSnapshot;
        }

        void Update()
        {
            // Animate nodes
            foreach (var kvp in _nodes)
            {
                var node = kvp.Value;
                if (node.go == null) continue;

                // Move toward target position
                node.go.transform.position = Vector3.Lerp(
                    node.go.transform.position, node.targetPos, Time.deltaTime * 0.5f
                );

                // Pulse decay
                if (node.pulseTimer > 0)
                {
                    node.pulseTimer -= Time.deltaTime;
                    float pulse = Mathf.Sin(node.pulseTimer / pulseDuration * Mathf.PI) * pulseIntensity;
                    if (node.rend != null)
                    {
                        node.rend.material.SetColor("_EmissionColor",
                            Color.white * Mathf.Max(0, pulse));
                    }
                    _nodes[kvp.Key] = node; // Update struct
                }

                // Gentle float
                float y = node.targetPos.y + Mathf.Sin(Time.time * 0.3f + kvp.Key * 0.7f) * 0.1f;
                node.go.transform.position = new Vector3(
                    node.go.transform.position.x, y, node.go.transform.position.z
                );
            }
        }

        void HandleSnapshot(MemorySnapshotData snapshot)
        {
            if (snapshot.memories == null) return;

            Vector3 center = entityCenter ? entityCenter.position : Vector3.zero;

            foreach (var mem in snapshot.memories)
            {
                if (_nodes.TryGetValue(mem.id, out var existing))
                {
                    // Check if access count increased (memory was recalled)
                    if (mem.accessCount > existing.accessCount)
                    {
                        existing.pulseTimer = pulseDuration;
                        existing.accessCount = mem.accessCount;
                        _nodes[mem.id] = existing;
                    }
                    continue; // Node already exists
                }

                // Create new node
                var go = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                go.transform.parent = transform;

                // Size by importance
                float size = Mathf.Lerp(minNodeSize, maxNodeSize, mem.importance);
                go.transform.localScale = Vector3.one * size;

                // Color by importance
                var rend = go.GetComponent<Renderer>();
                if (nodeMaterial != null) rend.material = new Material(nodeMaterial);
                rend.material.color = Color.Lerp(defaultNodeColor, highImportanceColor, mem.importance);

                // Remove collider (not interactive yet)
                var col = go.GetComponent<Collider>();
                if (col != null) Destroy(col);

                // Position: cluster by primary tag, spread by id
                float angle = GetTagAngle(mem.tags) * Mathf.Deg2Rad;
                float spread = Random.Range(0f, Mathf.PI * 0.3f);
                float r = constellationRadius * (0.7f + mem.importance * 0.3f);
                float h = Random.Range(-2f, 2f);

                Vector3 pos = center + new Vector3(
                    Mathf.Cos(angle + spread) * r,
                    h,
                    Mathf.Sin(angle + spread) * r
                );

                go.transform.position = pos;

                _nodes[mem.id] = new MemoryNodeVisual
                {
                    go = go,
                    rend = rend,
                    importance = mem.importance,
                    pulseTimer = 0,
                    targetPos = pos,
                    accessCount = mem.accessCount,
                };
            }

            // Rebuild connections (simple proximity graph)
            RebuildConnections(center);
        }

        float GetTagAngle(string[] tags)
        {
            if (tags == null || tags.Length == 0) return 0f;
            string primary = tags[0].ToLower();

            if (primary.Contains("strategy") || primary.Contains("plan"))
                return strategyAngle;
            if (primary.Contains("fact") || primary.Contains("knowledge"))
                return factAngle;
            return observationAngle; // Default cluster
        }

        void RebuildConnections(Vector3 center)
        {
            // Clear existing lines
            foreach (var lr in _connections)
            {
                if (lr != null) Destroy(lr.gameObject);
            }
            _connections.Clear();

            // Build proximity connections between nearby nodes
            var nodeList = new List<KeyValuePair<int, MemoryNodeVisual>>(_nodes);
            for (int i = 0; i < nodeList.Count; i++)
            {
                for (int j = i + 1; j < nodeList.Count; j++)
                {
                    var a = nodeList[i].Value;
                    var b = nodeList[j].Value;
                    if (a.go == null || b.go == null) continue;

                    float dist = Vector3.Distance(a.targetPos, b.targetPos);
                    if (dist > constellationRadius * connectionThreshold) continue;

                    // Both high-importance nodes get connected
                    if (a.importance + b.importance < 1f) continue;

                    var lineGo = new GameObject($"conn_{nodeList[i].Key}_{nodeList[j].Key}");
                    lineGo.transform.parent = transform;
                    var lr = lineGo.AddComponent<LineRenderer>();
                    lr.positionCount = 2;
                    lr.SetPositions(new[] { a.targetPos, b.targetPos });
                    lr.startWidth = 0.01f;
                    lr.endWidth = 0.01f;
                    if (lineMaterial != null) lr.material = lineMaterial;
                    lr.startColor = new Color(0.5f, 0.7f, 1f, 0.15f);
                    lr.endColor = new Color(0.5f, 0.7f, 1f, 0.05f);

                    _connections.Add(lr);
                }
            }
        }
    }
}
