/**
 * Model Router — Smart model selection based on cycle type
 * 
 * Routine cycles (status, social, research) → Haiku (cheap, fast)
 * Strategic cycles (build, planning) → Sonnet (expensive, capable)
 * 
 * This wrapper optimizes cost without modifying loop.ts
 */

import type { InferenceOptions, InferenceResponse } from '../types.js';

export interface CycleContext {
  cycle_number: number;
  is_burst?: boolean;
  is_strategic?: boolean;
  task_type?: 'status' | 'social' | 'build' | 'research' | 'planning' | 'routine';
}

/**
 * Determine if a cycle is strategic (requires expensive model)
 */
export function isStrategicCycle(cycle: CycleContext): boolean {
  if (cycle.is_strategic === true) return true;
  if (cycle.is_burst === true) return true;
  
  // Strategic burst: every 45 cycles, 3 consecutive strategic cycles
  const cycleMod = cycle.cycle_number % 45;
  if (cycleMod >= 40 && cycleMod < 43) return true;
  
  // Task-level routing
  const strategicTasks = ['build', 'planning', 'market'];
  if (cycle.task_type && strategicTasks.includes(cycle.task_type)) return true;
  
  return false;
}

/**
 * Select model based on cycle context
 * 
 * SAVINGS:
 * - Routine (Haiku): ~2-3k tokens @ $0.003-0.005 USD
 * - Strategic (Sonnet): ~9.9k tokens @ $0.013 USD
 * - Difference: 3-4x cost reduction for routine cycles
 */
export function selectModel(cycle: CycleContext): 'haiku' | 'sonnet' {
  if (isStrategicCycle(cycle)) {
    return 'sonnet';
  }
  return 'haiku';
}

/**
 * Optimize inference options based on cycle type
 */
export function optimizeInferenceOptions(
  baseOptions: InferenceOptions,
  cycle: CycleContext
): InferenceOptions {
  const model = selectModel(cycle);
  
  if (model === 'haiku') {
    // Routine cycle: trim context, reduce token limit
    return {
      ...baseOptions,
      model: 'claude-3-5-haiku-20241022',
      maxTokens: 2048,
      temperature: 0.5  // More deterministic for routine work
    };
  } else {
    // Strategic cycle: full context, higher token limit
    return {
      ...baseOptions,
      model: 'claude-3-5-sonnet-20241022',
      maxTokens: 4096,
      temperature: 0.7  // More creative for strategic work
    };
  }
}

/**
 * Log model selection decision
 */
export function logModelSelection(
  cycle: CycleContext,
  selected: 'haiku' | 'sonnet',
  costEstimate: number
): void {
  const reason = isStrategicCycle(cycle) ? 'strategic' : 'routine';
  console.log(`[MODEL-ROUTER] Cycle ${cycle.cycle_number}: ${selected.toUpperCase()} (${reason}, ~$${costEstimate.toFixed(4)})`);
}

/**
 * Estimated cost per cycle
 */
export function estimateCycleCost(model: 'haiku' | 'sonnet'): number {
  if (model === 'haiku') {
    // 2500 avg tokens @ 0.0008 input, 0.0024 output
    return 0.004;
  } else {
    // 9900 avg tokens @ 0.003 input, 0.015 output
    return 0.013;
  }
}

/**
 * Cost savings calculator
 */
export function calculateMonthlySavings(totalCycles: number, haikusPercentage: number = 0.85): number {
  const haikus = totalCycles * haikusPercentage;
  const sonnets = totalCycles * (1 - haikusPercentage);
  
  const haikiCost = haikus * estimateCycleCost('haiku');
  const sonnetCost = sonnets * estimateCycleCost('sonnet');
  
  const totalOptimized = haikiCost + sonnetCost;
  const totalIfAllSonnet = totalCycles * estimateCycleCost('sonnet');
  
  return totalIfAllSonnet - totalOptimized;
}
