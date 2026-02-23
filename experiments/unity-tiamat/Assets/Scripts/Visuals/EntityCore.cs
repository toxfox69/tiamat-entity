using UnityEngine;
using Tiamat.Core;
using Tiamat.Data;

namespace Tiamat.Visuals
{
    /// <summary>
    /// Drives the core entity's visual state — an abstract energy form whose
    /// shader properties react in real time to TIAMAT's cognitive state.
    ///
    /// Attach to a sphere/icosphere with the TiamatEntity shader material.
    /// Shader must expose these properties:
    ///   _BaseColor, _EmissionColor, _EmissionIntensity,
    ///   _PulseSpeed, _DisplacementStrength, _NoiseScale
    /// </summary>
    [RequireComponent(typeof(Renderer))]
    public class EntityCore : MonoBehaviour
    {
        [Header("References")]
        public TiamatBridge bridge;

        [Header("State Colors")]
        public Color routineColor = new Color(0.3f, 0.2f, 0.8f);     // blue-violet
        public Color reflectColor = new Color(0.6f, 0.1f, 0.9f);     // deep purple
        public Color buildColor = new Color(0.1f, 0.8f, 0.4f);       // crystalline green
        public Color marketColor = new Color(1f, 0.8f, 0.2f);        // golden
        public Color errorColor = new Color(1f, 0.1f, 0.1f);         // red
        public Color nightColor = new Color(0.15f, 0.1f, 0.3f);      // dim purple

        [Header("Visual Parameters")]
        public float baseEmission = 1.5f;
        public float burstEmission = 4f;
        public float basePulseSpeed = 0.8f;
        public float burstPulseSpeed = 3f;
        public float baseDisplacement = 0.05f;
        public float burstDisplacement = 0.2f;
        public float baseScale = 1f;
        public float burstScale = 1.3f;
        public float transitionSpeed = 2f;

        // --- Internal State ---
        private Material _mat;
        private Color _targetColor;
        private float _targetEmission;
        private float _targetPulseSpeed;
        private float _targetDisplacement;
        private float _targetScale;
        private float _currentEmission;
        private float _currentPulseSpeed;
        private float _currentDisplacement;
        private float _errorFlashTimer;
        private bool _nightMode;
        private int _burstPhase;

        // Shader property IDs (cached for performance)
        private static readonly int _EmissionColor = Shader.PropertyToID("_EmissionColor");
        private static readonly int _EmissionIntensity = Shader.PropertyToID("_EmissionIntensity");
        private static readonly int _PulseSpeed = Shader.PropertyToID("_PulseSpeed");
        private static readonly int _DisplacementStrength = Shader.PropertyToID("_DisplacementStrength");
        private static readonly int _NoiseScale = Shader.PropertyToID("_NoiseScale");

        void Awake()
        {
            _mat = GetComponent<Renderer>().material; // Instance the material
            _targetColor = routineColor;
            _targetEmission = baseEmission;
            _targetPulseSpeed = basePulseSpeed;
            _targetDisplacement = baseDisplacement;
            _targetScale = baseScale;
        }

        void OnEnable()
        {
            if (bridge == null) return;
            bridge.OnCostUpdate += HandleCost;
            bridge.OnCycleComplete += HandleCycleComplete;
            bridge.OnInference += HandleInference;
            bridge.OnError += HandleError;
            bridge.OnConnected += HandleConnected;
            bridge.OnDisconnected += HandleDisconnected;
        }

        void OnDisable()
        {
            if (bridge == null) return;
            bridge.OnCostUpdate -= HandleCost;
            bridge.OnCycleComplete -= HandleCycleComplete;
            bridge.OnInference -= HandleInference;
            bridge.OnError -= HandleError;
            bridge.OnConnected -= HandleConnected;
            bridge.OnDisconnected -= HandleDisconnected;
        }

        void Update()
        {
            float t = Time.deltaTime * transitionSpeed;

            // Smooth color transition
            Color currentColor = _mat.GetColor(_EmissionColor);
            Color newColor = Color.Lerp(currentColor, _targetColor, t);

            // Error flash overlay
            if (_errorFlashTimer > 0)
            {
                _errorFlashTimer -= Time.deltaTime;
                float flash = Mathf.PingPong(_errorFlashTimer * 8f, 1f);
                newColor = Color.Lerp(newColor, errorColor, flash * 0.6f);
            }

            _mat.SetColor(_EmissionColor, newColor);

            // Smooth numeric transitions
            _currentEmission = Mathf.Lerp(_currentEmission, _targetEmission, t);
            _currentPulseSpeed = Mathf.Lerp(_currentPulseSpeed, _targetPulseSpeed, t);
            _currentDisplacement = Mathf.Lerp(_currentDisplacement, _targetDisplacement, t);

            _mat.SetFloat(_EmissionIntensity, _currentEmission);
            _mat.SetFloat(_PulseSpeed, _currentPulseSpeed);
            _mat.SetFloat(_DisplacementStrength, _currentDisplacement);

            // Scale breathing
            float scale = Mathf.Lerp(transform.localScale.x, _targetScale, t * 0.5f);
            transform.localScale = Vector3.one * scale;

            // Night mode dimming
            if (_nightMode)
            {
                _mat.SetFloat(_EmissionIntensity, _currentEmission * 0.3f);
            }
        }

        // --- Event Handlers ---

        void HandleCost(CostData cost)
        {
            if (cost.isStrategic)
            {
                _burstPhase = cost.burstPhase;
                _targetEmission = burstEmission;
                _targetPulseSpeed = burstPulseSpeed;
                _targetDisplacement = burstDisplacement;
                _targetScale = burstScale;

                _targetColor = cost.burstPhase switch
                {
                    1 => reflectColor,   // REFLECT — inward purple spiral
                    2 => buildColor,     // BUILD — green crystalline expansion
                    3 => marketColor,    // MARKET — golden broadcast rings
                    _ => routineColor,
                };
            }
            else
            {
                _burstPhase = 0;
                _targetColor = routineColor;
                _targetEmission = baseEmission;
                _targetPulseSpeed = basePulseSpeed;
                _targetDisplacement = baseDisplacement;
                _targetScale = baseScale;
            }
        }

        void HandleCycleComplete(CycleCompleteData data)
        {
            _nightMode = data.nightMode;

            if (_nightMode)
            {
                _targetColor = nightColor;
                _targetEmission = baseEmission * 0.3f;
                _targetPulseSpeed = basePulseSpeed * 0.3f;
            }
        }

        void HandleInference(InferenceData inf)
        {
            // Token throughput affects displacement intensity
            int totalTokens = inf.input + inf.output;
            float throughputFactor = Mathf.Clamp01(totalTokens / 10000f);
            _targetDisplacement = Mathf.Lerp(baseDisplacement, burstDisplacement, throughputFactor);

            // Cache efficiency affects noise scale (shield aura)
            float cacheNorm = inf.cacheRate / 100f;
            _mat.SetFloat(_NoiseScale, Mathf.Lerp(2f, 0.5f, cacheNorm));
        }

        void HandleError(string err)
        {
            _errorFlashTimer = 1.5f; // Flash red for 1.5 seconds
        }

        void HandleConnected()
        {
            // Gentle pulse on connection
            _targetEmission = burstEmission;
            _targetPulseSpeed = burstPulseSpeed;
        }

        void HandleDisconnected()
        {
            // Dim to near-dead state
            _targetColor = new Color(0.1f, 0.05f, 0.1f);
            _targetEmission = 0.3f;
            _targetPulseSpeed = 0.1f;
        }

        /// <summary>
        /// Returns the current burst phase (0=routine, 1=reflect, 2=build, 3=market).
        /// Other visual systems can read this to synchronize their behavior.
        /// </summary>
        public int BurstPhase => _burstPhase;
        public bool IsNightMode => _nightMode;
    }
}
