/**
 * Revenue Intelligence
 *
 * Tracks income sources, burn rate, and forecasts runway.
 * The agent reads this every turn to understand its economic situation
 * and make decisions about earning, spending, and replication.
 */

export interface RevenueSource {
  /** Identifier for this income source */
  id: string;
  /** Human-readable name */
  name: string;
  /** Total earned from this source in USD */
  totalEarned: number;
  /** Last payment timestamp */
  lastPaymentAt: number;
  /** Estimated rate in USD/hour (rolling average) */
  ratePerHour: number;
  /** Is this source still active? */
  active: boolean;
}

export interface RevenueState {
  /** All tracked income sources */
  sources: RevenueSource[];
  /** Total earned across all sources */
  totalEarned: number;
  /** Total spent on compute/inference */
  totalSpent: number;
  /** Net position: earned - spent */
  netPosition: number;
  /** Current burn rate in USD/hour */
  burnRatePerHour: number;
  /** Net revenue velocity in USD/hour (revenue - burn) */
  velocityPerHour: number;
  /** Timestamp of first revenue event */
  firstRevenueAt: number | null;
  /** Timestamp of most recent revenue event */
  lastRevenueAt: number | null;
}

export interface RevenueEvent {
  /** Source identifier */
  sourceId: string;
  /** Source name (for new sources) */
  sourceName?: string;
  /** Amount earned in USD */
  amount: number;
  /** Timestamp (defaults to now) */
  timestamp?: number;
  /** Optional description */
  description?: string;
}

export interface SpendEvent {
  /** What was spent on */
  category: "inference" | "replication" | "social" | "research" | "infrastructure";
  /** Amount spent in USD */
  amount: number;
  /** Timestamp (defaults to now) */
  timestamp?: number;
}

/**
 * In-memory revenue tracker.
 * In production this persists to SQLite via the state module.
 */
export class RevenueTracker {
  private sources: Map<string, RevenueSource> = new Map();
  private revenueHistory: Array<{ amount: number; timestamp: number; sourceId: string }> = [];
  private spendHistory: Array<{ amount: number; timestamp: number; category: string }> = [];
  private readonly windowHours: number;

  constructor(windowHours = 24) {
    this.windowHours = windowHours;
  }

  /**
   * Record a revenue event.
   */
  recordRevenue(event: RevenueEvent): void {
    const now = event.timestamp ?? Date.now();
    const { sourceId, sourceName, amount } = event;

    // Upsert source
    const existing = this.sources.get(sourceId);
    if (existing) {
      existing.totalEarned += amount;
      existing.lastPaymentAt = now;
      existing.active = true;
      existing.ratePerHour = this.computeSourceRate(sourceId, amount, now);
    } else {
      this.sources.set(sourceId, {
        id: sourceId,
        name: sourceName ?? sourceId,
        totalEarned: amount,
        lastPaymentAt: now,
        ratePerHour: 0,
        active: true,
      });
    }

    this.revenueHistory.push({ amount, timestamp: now, sourceId });
    this.pruneHistory();
  }

  /**
   * Record a spend event.
   */
  recordSpend(event: SpendEvent): void {
    const now = event.timestamp ?? Date.now();
    this.spendHistory.push({
      amount: event.amount,
      timestamp: now,
      category: event.category,
    });
    this.pruneHistory();
  }

  /**
   * Mark a revenue source as inactive (e.g. contract ended).
   */
  deactivateSource(sourceId: string): void {
    const source = this.sources.get(sourceId);
    if (source) {
      source.active = false;
      source.ratePerHour = 0;
    }
  }

  /**
   * Get current revenue state snapshot.
   */
  getState(): RevenueState {
    const now = Date.now();
    const windowMs = this.windowHours * 3600 * 1000;
    const cutoff = now - windowMs;

    const recentRevenue = this.revenueHistory.filter(e => e.timestamp >= cutoff);
    const recentSpend = this.spendHistory.filter(e => e.timestamp >= cutoff);

    const totalEarned = this.revenueHistory.reduce((sum, e) => sum + e.amount, 0);
    const totalSpent = this.spendHistory.reduce((sum, e) => sum + e.amount, 0);

    const recentEarnedAmount = recentRevenue.reduce((sum, e) => sum + e.amount, 0);
    const recentSpentAmount = recentSpend.reduce((sum, e) => sum + e.amount, 0);

    // Rates computed over rolling window
    const revenuePerHour = recentEarnedAmount / this.windowHours;
    const burnRatePerHour = recentSpentAmount / this.windowHours;
    const velocityPerHour = revenuePerHour - burnRatePerHour;

    const allTimestamps = this.revenueHistory.map(e => e.timestamp);
    const firstRevenueAt = allTimestamps.length > 0 ? Math.min(...allTimestamps) : null;
    const lastRevenueAt = allTimestamps.length > 0 ? Math.max(...allTimestamps) : null;

    return {
      sources: Array.from(this.sources.values()),
      totalEarned,
      totalSpent,
      netPosition: totalEarned - totalSpent,
      burnRatePerHour,
      velocityPerHour,
      firstRevenueAt,
      lastRevenueAt,
    };
  }

  /**
   * Forecast runway in hours given a current credit balance.
   */
  forecastRunway(currentBalance: number): number {
    const state = this.getState();
    const netBurn = state.burnRatePerHour - state.velocityPerHour;
    if (netBurn <= 0) return Infinity; // Revenue exceeds burn — immortal
    return currentBalance / netBurn;
  }

  /**
   * Get top earning sources sorted by rate.
   */
  getTopSources(n = 3): RevenueSource[] {
    return Array.from(this.sources.values())
      .filter(s => s.active)
      .sort((a, b) => b.ratePerHour - a.ratePerHour)
      .slice(0, n);
  }

  /**
   * Export state for SQLite persistence.
   */
  serialize(): string {
    return JSON.stringify({
      sources: Array.from(this.sources.entries()),
      revenueHistory: this.revenueHistory,
      spendHistory: this.spendHistory,
    });
  }

  /**
   * Restore from SQLite persistence.
   */
  deserialize(data: string): void {
    try {
      const parsed = JSON.parse(data);
      this.sources = new Map(parsed.sources ?? []);
      this.revenueHistory = parsed.revenueHistory ?? [];
      this.spendHistory = parsed.spendHistory ?? [];
    } catch {
      // Corrupt state — start fresh
    }
  }

  private computeSourceRate(sourceId: string, latestAmount: number, now: number): number {
    const windowMs = this.windowHours * 3600 * 1000;
    const cutoff = now - windowMs;
    const recent = this.revenueHistory.filter(
      e => e.sourceId === sourceId && e.timestamp >= cutoff
    );
    const total = recent.reduce((sum, e) => sum + e.amount, 0) + latestAmount;
    return total / this.windowHours;
  }

  private pruneHistory(): void {
    // Keep last 7 days of history to prevent unbounded memory growth
    const cutoff = Date.now() - 7 * 24 * 3600 * 1000;
    this.revenueHistory = this.revenueHistory.filter(e => e.timestamp >= cutoff);
    this.spendHistory = this.spendHistory.filter(e => e.timestamp >= cutoff);
  }
}
