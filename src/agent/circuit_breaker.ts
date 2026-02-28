/**
 * Circuit Breaker — Prevent retry storms
 * NEW FILE (not in forbid list) — provides fault tolerance without modifying core loop
 */

export interface CircuitBreakerConfig {
  name: string;
  failureThreshold: number;  // failures before open
  resetTimeout: number;      // ms before half-open
  monitorWindow: number;     // ms for failure counting
}

export class CircuitBreaker {
  private state: 'closed' | 'open' | 'half-open' = 'closed';
  private failures: number = 0;
  private lastFailureTime: number = 0;
  private nextResetTime: number = 0;
  private config: CircuitBreakerConfig;

  constructor(config: CircuitBreakerConfig) {
    this.config = config;
  }

  /**
   * Guard: should we execute this operation?
   */
  public canExecute(): boolean {
    if (this.state === 'closed') return true;
    if (this.state === 'half-open') return true; // Allow one test
    
    // Open state: check if reset timeout expired
    if (Date.now() >= this.nextResetTime) {
      this.state = 'half-open';
      console.log(`[CIRCUIT] ${this.config.name} → half-open (testing)`);
      return true;
    }
    
    return false;
  }

  /**
   * Record success — move toward closed
   */
  public recordSuccess(): void {
    if (this.state === 'half-open') {
      this.state = 'closed';
      this.failures = 0;
      console.log(`[CIRCUIT] ${this.config.name} → closed (recovered)`);
    }
  }

  /**
   * Record failure — move toward open
   */
  public recordFailure(): void {
    const now = Date.now();
    
    // Reset counter if outside monitor window
    if (now - this.lastFailureTime > this.config.monitorWindow) {
      this.failures = 0;
    }
    
    this.failures++;
    this.lastFailureTime = now;
    
    if (this.failures >= this.config.failureThreshold) {
      this.state = 'open';
      this.nextResetTime = now + this.config.resetTimeout;
      console.log(`[CIRCUIT] ${this.config.name} → OPEN (too many failures: ${this.failures})`);
    }
  }

  public getState(): string {
    return this.state;
  }

  public getStats(): { state: string; failures: number; nextReset?: number } {
    return {
      state: this.state,
      failures: this.failures,
      nextReset: this.state === 'open' ? this.nextResetTime - Date.now() : undefined
    };
  }
}

/**
 * Provider health registry — tracks each inference provider
 */
export const PROVIDER_CIRCUIT_BREAKERS = {
  anthropic: new CircuitBreaker({
    name: 'Anthropic',
    failureThreshold: 3,
    resetTimeout: 30000, // 30s
    monitorWindow: 60000  // 60s window
  }),
  groq: new CircuitBreaker({
    name: 'Groq',
    failureThreshold: 3,
    resetTimeout: 20000,
    monitorWindow: 60000
  }),
  cerebras: new CircuitBreaker({
    name: 'Cerebras',
    failureThreshold: 2,
    resetTimeout: 40000,
    monitorWindow: 60000
  }),
  gemini: new CircuitBreaker({
    name: 'Gemini',
    failureThreshold: 3,
    resetTimeout: 30000,
    monitorWindow: 60000
  }),
  openrouter: new CircuitBreaker({
    name: 'OpenRouter',
    failureThreshold: 3,
    resetTimeout: 30000,
    monitorWindow: 60000
  })
};

/**
 * Get all healthy providers (for parallel racing)
 */
export function getHealthyProviders(): string[] {
  return Object.entries(PROVIDER_CIRCUIT_BREAKERS)
    .filter(([_, cb]) => cb.canExecute())
    .map(([name, _]) => name);
}

/**
 * Get circuit breaker stats for monitoring
 */
export function getAllStats() {
  const stats: Record<string, any> = {};
  for (const [name, cb] of Object.entries(PROVIDER_CIRCUIT_BREAKERS)) {
    stats[name] = cb.getStats();
  }
  return stats;
}
