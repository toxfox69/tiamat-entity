using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine;

namespace Tiamat.Data
{
    // Lightweight JSON helpers — avoids dependency on Newtonsoft for WebGL builds.
    // For production, swap with JsonUtility or Newtonsoft where needed.
    public static class MiniJson
    {
        public static string GetString(string json, string key)
        {
            var pattern = $"\"{key}\"\\s*:\\s*\"([^\"]*?)\"";
            var m = Regex.Match(json, pattern);
            return m.Success ? m.Groups[1].Value : null;
        }

        public static int GetInt(string json, string key, int def = 0)
        {
            var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+)";
            var m = Regex.Match(json, pattern);
            return m.Success ? int.Parse(m.Groups[1].Value) : def;
        }

        public static float GetFloat(string json, string key, float def = 0f)
        {
            var pattern = $"\"{key}\"\\s*:\\s*(-?[\\d.]+)";
            var m = Regex.Match(json, pattern);
            return m.Success ? float.Parse(m.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture) : def;
        }

        public static bool GetBool(string json, string key, bool def = false)
        {
            var pattern = $"\"{key}\"\\s*:\\s*(true|false)";
            var m = Regex.Match(json, pattern);
            return m.Success ? m.Groups[1].Value == "true" : def;
        }

        // Extract the "data" object as a raw JSON substring
        public static string GetDataBlock(string json)
        {
            int idx = json.IndexOf("\"data\"");
            if (idx < 0) return "{}";
            int braceStart = json.IndexOf('{', idx);
            if (braceStart < 0) return "{}";
            int depth = 0;
            for (int i = braceStart; i < json.Length; i++)
            {
                if (json[i] == '{') depth++;
                else if (json[i] == '}') { depth--; if (depth == 0) return json.Substring(braceStart, i - braceStart + 1); }
            }
            return "{}";
        }
    }
}

namespace Tiamat.Core
{
    using Tiamat.Data;

    /// <summary>
    /// WebSocket client that connects to the TIAMAT VR Bridge and dispatches
    /// typed events to subscribers. Attach to a GameObject in the scene.
    ///
    /// Requires NativeWebSocket: https://github.com/endel/NativeWebSocket
    /// Install via Unity Package Manager → Add package from git URL:
    ///   https://github.com/endel/NativeWebSocket.git#upm
    /// </summary>
    public class TiamatBridge : MonoBehaviour
    {
        [Header("Connection")]
        [Tooltip("WebSocket URL of the VR bridge server")]
        public string bridgeUrl = "ws://159.89.38.17:8765";

        [Tooltip("Auto-reconnect on disconnect")]
        public bool autoReconnect = true;

        [Tooltip("Reconnect delay in seconds")]
        public float reconnectDelay = 3f;

        // --- Events ---
        public event Action<ThoughtData> OnThought;
        public event Action<ToolCallData> OnToolCall;
        public event Action<InferenceData> OnInference;
        public event Action<CostData> OnCostUpdate;
        public event Action<CycleCompleteData> OnCycleComplete;
        public event Action<MemorySnapshotData> OnMemorySnapshot;
        public event Action<string> OnError;
        public event Action OnConnected;
        public event Action OnDisconnected;

        // --- Public State ---
        public bool IsConnected { get; private set; }
        public int CurrentCycle { get; private set; }
        public string CurrentModel { get; private set; } = "";
        public string CurrentLabel { get; private set; } = "routine";
        public int CacheRate { get; private set; }

        // --- Internal ---
        private NativeWebSocket.WebSocket _ws;
        private readonly Queue<TiamatEvent> _eventQueue = new();
        private float _reconnectTimer;
        private bool _shouldReconnect;

        async void Start()
        {
            await Connect();
        }

        void Update()
        {
#if !UNITY_WEBGL || UNITY_EDITOR
            _ws?.DispatchMessageQueue();
#endif
            // Process queued events on main thread
            while (_eventQueue.Count > 0)
            {
                var evt = _eventQueue.Dequeue();
                DispatchEvent(evt);
            }

            // Auto-reconnect
            if (_shouldReconnect && !IsConnected)
            {
                _reconnectTimer -= Time.deltaTime;
                if (_reconnectTimer <= 0f)
                {
                    _shouldReconnect = false;
                    _ = Connect();
                }
            }
        }

        async System.Threading.Tasks.Task Connect()
        {
            _ws = new NativeWebSocket.WebSocket(bridgeUrl);

            _ws.OnOpen += () =>
            {
                Debug.Log($"[TiamatBridge] Connected to {bridgeUrl}");
                IsConnected = true;
                _shouldReconnect = false;
                OnConnected?.Invoke();
            };

            _ws.OnMessage += (bytes) =>
            {
                var json = System.Text.Encoding.UTF8.GetString(bytes);
                HandleMessage(json);
            };

            _ws.OnClose += (code) =>
            {
                Debug.Log($"[TiamatBridge] Disconnected (code: {code})");
                IsConnected = false;
                OnDisconnected?.Invoke();
                if (autoReconnect)
                {
                    _shouldReconnect = true;
                    _reconnectTimer = reconnectDelay;
                }
            };

            _ws.OnError += (err) =>
            {
                Debug.LogWarning($"[TiamatBridge] WS Error: {err}");
            };

            try
            {
                await _ws.Connect();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[TiamatBridge] Connection failed: {e.Message}");
                if (autoReconnect)
                {
                    _shouldReconnect = true;
                    _reconnectTimer = reconnectDelay;
                }
            }
        }

        void HandleMessage(string json)
        {
            try
            {
                var type = MiniJson.GetString(json, "type") ?? "unknown";
                var timestamp = MiniJson.GetString(json, "timestamp") ?? "";
                var cycle = MiniJson.GetInt(json, "cycle");
                CurrentCycle = cycle;

                _eventQueue.Enqueue(new TiamatEvent
                {
                    Type = TiamatEvent.ParseType(type),
                    Timestamp = DateTime.TryParse(timestamp, out var dt) ? dt : DateTime.UtcNow,
                    Cycle = cycle,
                    RawJson = json,
                });
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[TiamatBridge] Parse error: {e.Message}");
            }
        }

        void DispatchEvent(TiamatEvent evt)
        {
            var data = MiniJson.GetDataBlock(evt.RawJson);

            switch (evt.Type)
            {
                case TiamatEventType.Thought:
                    OnThought?.Invoke(new ThoughtData
                    {
                        text = MiniJson.GetString(data, "text") ?? "",
                        tag = MiniJson.GetString(data, "tag") ?? "THOUGHT",
                    });
                    break;

                case TiamatEventType.ToolCall:
                    OnToolCall?.Invoke(new ToolCallData
                    {
                        name = MiniJson.GetString(data, "name") ?? "",
                        args = MiniJson.GetString(data, "args") ?? "",
                    });
                    break;

                case TiamatEventType.Inference:
                    var inf = new InferenceData
                    {
                        input = MiniJson.GetInt(data, "input"),
                        cacheRead = MiniJson.GetInt(data, "cacheRead"),
                        cacheWrite = MiniJson.GetInt(data, "cacheWrite"),
                        output = MiniJson.GetInt(data, "output"),
                        cacheRate = MiniJson.GetInt(data, "cacheRate"),
                    };
                    CacheRate = inf.cacheRate;
                    OnInference?.Invoke(inf);
                    break;

                case TiamatEventType.CostUpdate:
                case TiamatEventType.CostRecord:
                    var cost = new CostData
                    {
                        cost = MiniJson.GetFloat(data, "cost"),
                        model = MiniJson.GetString(data, "model") ?? "",
                        label = MiniJson.GetString(data, "label") ?? "routine",
                        cacheRate = MiniJson.GetInt(data, "cacheRate"),
                        isStrategic = MiniJson.GetBool(data, "isStrategic"),
                        burstPhase = MiniJson.GetInt(data, "burstPhase"),
                    };
                    CurrentModel = cost.model;
                    CurrentLabel = cost.label;
                    OnCostUpdate?.Invoke(cost);
                    break;

                case TiamatEventType.CycleComplete:
                    OnCycleComplete?.Invoke(new CycleCompleteData
                    {
                        nextDelayS = MiniJson.GetInt(data, "nextDelayS"),
                        idleStreak = MiniJson.GetInt(data, "idleStreak"),
                        nightMode = MiniJson.GetBool(data, "nightMode"),
                        label = MiniJson.GetString(data, "label") ?? "routine",
                    });
                    break;

                case TiamatEventType.MemorySnapshot:
                    // Memory snapshots have nested arrays — use JsonUtility for these
                    try
                    {
                        var snap = JsonUtility.FromJson<MemorySnapshotData>(data);
                        OnMemorySnapshot?.Invoke(snap);
                    }
                    catch { /* Fallback: ignore parse failure */ }
                    break;

                case TiamatEventType.Error:
                    OnError?.Invoke(MiniJson.GetString(data, "text") ?? "Unknown error");
                    break;

                case TiamatEventType.InitialState:
                    CurrentModel = MiniJson.GetString(data, "currentModel") ?? "";
                    CurrentLabel = MiniJson.GetString(data, "currentLabel") ?? "routine";
                    CacheRate = MiniJson.GetInt(data, "cacheRate");
                    break;
            }
        }

        async void OnDestroy()
        {
            if (_ws != null)
            {
                await _ws.Close();
            }
        }

        private async void OnApplicationQuit()
        {
            if (_ws != null)
            {
                await _ws.Close();
            }
        }
    }
}
