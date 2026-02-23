using System;
using System.Collections.Generic;
using UnityEngine;

namespace Tiamat.Data
{
    /// <summary>
    /// All event types the WebSocket bridge can emit.
    /// </summary>
    public enum TiamatEventType
    {
        Thought,
        ToolCall,
        ToolResult,
        Inference,
        CostUpdate,
        CostRecord,
        CycleComplete,
        Error,
        MemorySnapshot,
        Heartbeat,
        InitialState,
        InitialThoughts,
        Unknown
    }

    [Serializable]
    public class TiamatMessage
    {
        public string type;
        public string timestamp;
        public int cycle;
        public string data; // Raw JSON — deserialized per type
    }

    [Serializable]
    public class ThoughtData
    {
        public string text;
        public string tag;
    }

    [Serializable]
    public class ToolCallData
    {
        public string name;
        public string args;
    }

    [Serializable]
    public class InferenceData
    {
        public int input;
        public int cacheRead;
        public int cacheWrite;
        public int output;
        public int cacheRate;
    }

    [Serializable]
    public class CostData
    {
        public float cost;
        public string model;
        public string label;
        public int cacheRate;
        public bool isStrategic;
        public int burstPhase;
    }

    [Serializable]
    public class CycleCompleteData
    {
        public int nextDelayS;
        public int idleStreak;
        public bool nightMode;
        public string label;
    }

    [Serializable]
    public class MemoryNode
    {
        public int id;
        public float importance;
        public string[] tags;
        public int accessCount;
        public string contentPreview;
    }

    [Serializable]
    public class MemorySnapshotData
    {
        public int total;
        public MemoryNode[] memories;
    }

    [Serializable]
    public class InitialStateData
    {
        public CostData[] costHistory;
        public string currentModel;
        public string currentLabel;
        public int cacheRate;
    }

    /// <summary>
    /// Parsed, typed event ready for consumption by visual systems.
    /// </summary>
    public struct TiamatEvent
    {
        public TiamatEventType Type;
        public DateTime Timestamp;
        public int Cycle;
        public string RawJson;

        public static TiamatEventType ParseType(string type)
        {
            return type switch
            {
                "thought" => TiamatEventType.Thought,
                "tool_call" => TiamatEventType.ToolCall,
                "tool_result" => TiamatEventType.ToolResult,
                "inference" => TiamatEventType.Inference,
                "cost_update" => TiamatEventType.CostUpdate,
                "cost_record" => TiamatEventType.CostRecord,
                "cycle_complete" => TiamatEventType.CycleComplete,
                "error" => TiamatEventType.Error,
                "memory_snapshot" => TiamatEventType.MemorySnapshot,
                "heartbeat" => TiamatEventType.Heartbeat,
                "initial_state" => TiamatEventType.InitialState,
                "initial_thoughts" => TiamatEventType.InitialThoughts,
                _ => TiamatEventType.Unknown
            };
        }
    }
}
