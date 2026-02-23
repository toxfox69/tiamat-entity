using System.Collections.Generic;
using UnityEngine;
using Tiamat.Core;
using Tiamat.Data;

namespace Tiamat.Visuals
{
    /// <summary>
    /// Visualizes TIAMAT's financial flow as a thin golden stream draining
    /// from the entity each cycle. Width = cost. Cache efficiency = shield aura.
    ///
    /// Uses a LineRenderer with animated UV scroll for the "flow" effect,
    /// plus a transparent sphere for the cache shield.
    /// </summary>
    public class CostFlowVisualizer : MonoBehaviour
    {
        [Header("References")]
        public TiamatBridge bridge;
        public Transform entityCenter;

        [Header("Flow Stream")]
        public LineRenderer flowLine;
        public float minWidth = 0.005f;
        public float maxWidth = 0.06f;
        public float flowLength = 4f;
        public float scrollSpeed = 2f;
        public Color flowColor = new Color(1f, 0.85f, 0.2f, 0.6f);

        [Header("Cache Shield")]
        [Tooltip("Transparent sphere around entity — brighter = higher cache rate")]
        public Renderer cacheShield;
        public Color shieldColor = new Color(0.3f, 0.6f, 1f, 0.1f);
        public float maxShieldAlpha = 0.25f;

        [Header("Cost Display")]
        public TMPro.TextMeshPro costText;
        public TMPro.TextMeshPro dailyCostText;

        // --- State ---
        private float _currentWidth;
        private float _targetWidth;
        private float _currentShieldAlpha;
        private float _targetShieldAlpha;
        private float _totalCostToday;
        private float _lastCycleCost;
        private float _uvOffset;

        void OnEnable()
        {
            if (bridge == null) return;
            bridge.OnCostUpdate += HandleCost;
            bridge.OnInference += HandleInference;
        }

        void OnDisable()
        {
            if (bridge == null) return;
            bridge.OnCostUpdate -= HandleCost;
            bridge.OnInference -= HandleInference;
        }

        void Update()
        {
            // Smooth width transition
            _currentWidth = Mathf.Lerp(_currentWidth, _targetWidth, Time.deltaTime * 3f);

            if (flowLine != null)
            {
                flowLine.startWidth = _currentWidth;
                flowLine.endWidth = _currentWidth * 0.3f;

                // Position the flow line from entity downward
                Vector3 start = entityCenter ? entityCenter.position : Vector3.zero;
                Vector3 end = start + Vector3.down * flowLength;
                flowLine.SetPosition(0, start);
                flowLine.SetPosition(1, end);

                // Animate UV scroll for flow effect
                _uvOffset += Time.deltaTime * scrollSpeed;
                flowLine.material.SetTextureOffset("_MainTex", new Vector2(0, -_uvOffset));
            }

            // Cache shield alpha
            _currentShieldAlpha = Mathf.Lerp(_currentShieldAlpha, _targetShieldAlpha, Time.deltaTime * 2f);
            if (cacheShield != null)
            {
                var c = shieldColor;
                c.a = _currentShieldAlpha;
                cacheShield.material.color = c;
            }
        }

        void HandleCost(CostData cost)
        {
            _lastCycleCost = cost.cost;
            _totalCostToday += cost.cost;

            // Map cost to stream width: routine ~0.004 → thin, burst ~0.037 → thick
            float normalized = Mathf.InverseLerp(0.001f, 0.04f, cost.cost);
            _targetWidth = Mathf.Lerp(minWidth, maxWidth, normalized);

            // Update text displays
            if (costText != null)
                costText.text = $"${cost.cost:F4}";
            if (dailyCostText != null)
                dailyCostText.text = $"Daily: ${_totalCostToday:F3}";
        }

        void HandleInference(InferenceData inf)
        {
            // Cache rate → shield brightness
            float cacheNorm = inf.cacheRate / 100f;
            _targetShieldAlpha = Mathf.Lerp(0.02f, maxShieldAlpha, cacheNorm);
        }
    }
}
