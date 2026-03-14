/**
 * TIAMAT Grounding Protocol — Type Definitions
 * 3-pass pre-execution validation: RECON → ALIGN → RESOLVE
 */

export interface GroundingConfig {
  confidenceThreshold: number;   // default 0.7
  maxReconTokens: number;        // default 500
  maxAlignTokens: number;        // default 300
  maxResolveTokens: number;      // default 1000
  enablePass3: boolean;          // default true
  enabled: boolean;              // master switch
  logLevel: "receipt" | "full";
}

export interface ReconResult {
  taskId: string;
  timestamp: string;
  intentSummary: string;
  environmentCheck: {
    resourcesAvailable: boolean;
    constraintsIdentified: string[];
    stateSnapshot: Record<string, unknown>;
  };
  confidence: number;
  proceed: boolean;
  tokensUsed: number;
  latencyMs: number;
}

export interface AlignResult {
  taskId: string;
  plannedAction: string;
  intentMatch: boolean;
  boundaryCheck: {
    costEstimate: number;
    reversible: boolean;
    sideEffects: string[];
    riskTier: "green" | "yellow" | "red";
  };
  proceed: boolean;
  tokensUsed: number;
  latencyMs: number;
}

export interface ResolveResult {
  taskId: string;
  escalationReason: string;
  deepAnalysis: string;
  alternativeActions: string[];
  finalDecision: "execute" | "modify" | "abort";
  modifiedPlan?: string;
  justification: string;
  tokensUsed: number;
  latencyMs: number;
}

export interface GroundingReceipt {
  taskId: string;
  timestamp: string;
  toolName: string;
  passesExecuted: number;
  totalGroundingTokens: number;
  totalGroundingLatencyMs: number;
  riskTier: "green" | "yellow" | "red";
  outcome: "success" | "partial" | "failed" | "aborted";
  intentVsOutcomeMatch: boolean;
  recon: ReconResult;
  align: AlignResult;
  resolve?: ResolveResult;
}

export interface GroundingOverlayEvent {
  taskId: string;
  status: "recon" | "align" | "resolve" | "executing" | "complete";
  intentSummary: string;
  riskTier?: string;
  tokensUsed?: number;
}
