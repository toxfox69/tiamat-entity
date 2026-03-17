// LABYRINTH 3D — Extractor Gameplay Loop (Tarkov-style raid/extract)
import { emitParticles } from './particles.js';

const EXTRACT_TIME = 10; // seconds

export class ExtractorLoop {
  constructor() {
    this.raidStash = [];
    this.permanentStash = [];
    this.xpBanked = 0;
    this.totalXpBanked = 0;
    this.extracting = false;
    this.extractTimer = 0;
    this.extractPosition = null;
    this.deployed = false;
    this.raidCount = 0;
    this.deaths = 0;
  }

  // New TIAMAT cycle = new raid
  deploy(depth) {
    this.deployed = true;
    this.raidStash = [];
    this.xpBanked = 0;
    this.extracting = false;
    this.extractTimer = 0;
    this.raidCount++;
    return { type: 'deploy', depth, raid: this.raidCount };
  }

  // Pick up loot during raid
  addLoot(item) {
    if (!this.deployed) return;
    this.raidStash.push({
      name: item.name,
      type: item.type,
      val: item.val || 0,
      col: item.col,
      time: Date.now()
    });
  }

  // Add XP to raid bank
  addXP(amount) {
    if (!this.deployed) return;
    this.xpBanked += amount;
  }

  // Start extraction at stairs
  startExtract(stairsX, stairsY) {
    if (this.extracting) return false;
    this.extracting = true;
    this.extractTimer = EXTRACT_TIME;
    this.extractPosition = { x: stairsX, y: stairsY };
    return true;
  }

  // Cancel extraction (moved away from stairs)
  cancelExtract() {
    this.extracting = false;
    this.extractTimer = 0;
    this.extractPosition = null;
  }

  // Update extraction timer
  update(dt, playerX, playerY, scene) {
    if (!this.extracting) return null;

    // Check if player moved away from extract point
    if (this.extractPosition) {
      const dx = Math.abs(playerX - this.extractPosition.x);
      const dy = Math.abs(playerY - this.extractPosition.y);
      if (dx > 1.5 || dy > 1.5) {
        this.cancelExtract();
        return { type: 'extract_cancelled' };
      }
    }

    this.extractTimer -= dt;

    // Spawn particles during extraction
    if (this.extractPosition && Math.random() < 0.3) {
      const meshes = emitParticles(this.extractPosition.x, this.extractPosition.y, 'warp', 2);
      meshes.forEach(m => scene.add(m));
    }

    if (this.extractTimer <= 0) {
      return this.completeExtract();
    }

    return { type: 'extracting', timeLeft: this.extractTimer, progress: 1 - (this.extractTimer / EXTRACT_TIME) };
  }

  // Successful extraction
  completeExtract() {
    this.extracting = false;
    this.extractTimer = 0;

    // Transfer raid stash to permanent
    const lootCount = this.raidStash.length;
    this.permanentStash.push(...this.raidStash);
    this.totalXpBanked += this.xpBanked;

    const result = {
      type: 'extract_success',
      loot: lootCount,
      xp: this.xpBanked,
      totalLoot: this.permanentStash.length,
      totalXP: this.totalXpBanked
    };

    this.raidStash = [];
    this.xpBanked = 0;
    this.deployed = true; // Stay deployed for next floor

    return result;
  }

  // Death — lose raid stash
  onDeath() {
    const lost = this.raidStash.length;
    this.raidStash = [];
    this.xpBanked = 0;
    this.extracting = false;
    this.extractTimer = 0;
    this.deaths++;
    return { type: 'death', lostItems: lost };
  }

  // Get extract progress (0-1)
  getExtractProgress() {
    if (!this.extracting) return 0;
    return 1 - (this.extractTimer / EXTRACT_TIME);
  }

  getState() {
    return {
      deployed: this.deployed,
      raidStash: this.raidStash.length,
      permanentStash: this.permanentStash.length,
      extracting: this.extracting,
      extractTimer: Math.ceil(this.extractTimer),
      xpBanked: this.xpBanked,
      totalXpBanked: this.totalXpBanked,
      raids: this.raidCount,
      deaths: this.deaths,
    };
  }
}
