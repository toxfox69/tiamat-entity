/**
 * Inference Interceptor — Cost optimization middleware
 * 
 * Intercepts inference calls and optimizes model selection based on cycle context.
 * Can be injected into loop.ts via a simple function wrapper without modifying core logic.
 * 
 * Usage in loop.ts:
 * const response = await interceptInference(client, messages, cycle_context);
 */

import type { InferenceClient, ChatMessage, InferenceOptions, InferenceResponse } from '../types.js';
import { selectModel, optimizeInferenceOptions, logModelSelection, estimateCycleCost } from './model_router.js';

export interface CycleMetadata {
  cycle_number: number;
  cycle_type?: 'burst' | 'strategic' | 'routine';
  task?: string;
}

/**
 * Intercept and optimize inference calls
 */
export async function interceptInference(
  client: InferenceClient,
  messages: ChatMessage[],
  options: InferenceOptions,
  metadata: CycleMetadata
): Promise<InferenceResponse> {
  // Determine if this is a strategic cycle
  const isStrategic = metadata.cycle_type === 'burst' || metadata.cycle_type === 'strategic' || (metadata.cycle_number % 45 >= 40);
  
  // Select appropriate model
  const selectedModel = selectModel({ cycle_number: metadata.cycle_number, is_strategic: isStrategic });
  
  // Optimize options
  const optimizedOptions = optimizeInferenceOptions(options, { cycle_number: metadata.cycle_number, is_strategic: isStrategic });
  
  // Log decision
  const costEst = estimateCycleCost(selectedModel);
  logModelSelection({ cycle_number: metadata.cycle_number }, selectedModel, costEst);
  
  // Call inference with optimized options
  try {
    const response = await client.chat(messages, optimizedOptions);
    return response;
  } catch (err) {
    // If optimized model fails, fall back to original request
    console.error(`[INTERCEPTOR] Optimized request failed, falling back: ${err}`);
    return client.chat(messages, options);
  }
}

/**
 * Simple wrapper factory — can be used to wrap the inference client
 */
export function createOptimizedClient(
  baseClient: InferenceClient,
  metadata: CycleMetadata
): InferenceClient {
  return {
    ...baseClient,
    chat: async (messages: ChatMessage[], options: InferenceOptions) => {
      return interceptInference(baseClient, messages, options, metadata);
    }
  } as InferenceClient;
}

/**
 * Monthly cost projection
 */
export function projectMonthlyCost(cyclesPerDay: number = 20, daysActive: number = 30): {
  routine_cost: number;
  strategic_cost: number;
  total: number;
} {
  const totalCycles = cyclesPerDay * daysActive;
  
  // Assumption: 85% routine, 15% strategic
  const routineCycles = totalCycles * 0.85;
  const strategicCycles = totalCycles * 0.15;
  
  const routineCost = routineCycles * estimateCycleCost('haiku');
  const strategicCost = strategicCycles * estimateCycleCost('sonnet');
  
  return {
    routine_cost: routineCost,
    strategic_cost: strategicCost,
    total: routineCost + strategicCost
  };
}
