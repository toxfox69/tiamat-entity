/**
 * TIAMAT Bluesky Engagement Analytics
 * Tracks post performance, engagement trends, optimal posting times
 */

import * as path from 'path';

const ANALYTICS_DB = path.join('/root/.automaton', 'bluesky_analytics.db');

interface BlueskyPost {
  uri: string;
  text: string;
  created_at: string;
  likes: number;
  reposts: number;
  replies: number;
  fetched_at: string;
}

interface PostMetrics {
  uri: string;
  text: string;
  created_at: string;
  likes: number;
  reposts: number;
  replies: number;
  engagement_rate: number; // (likes + reposts + replies) / text.length
  hours_old: number;
}

/**
 * Initialize analytics database
 */
function initDB() {
  const db = new (require('better-sqlite3'))(ANALYTICS_DB);

  db.exec(`
    CREATE TABLE IF NOT EXISTS posts (
      uri TEXT PRIMARY KEY,
      text TEXT,
      created_at TEXT,
      likes INTEGER DEFAULT 0,
      reposts INTEGER DEFAULT 0,
      replies INTEGER DEFAULT 0,
      fetched_at TEXT,
      UNIQUE(uri)
    );

    CREATE TABLE IF NOT EXISTS metrics (
      id INTEGER PRIMARY KEY,
      uri TEXT,
      engagement_rate REAL,
      hour_posted INTEGER,
      day_of_week TEXT,
      text_length INTEGER,
      recorded_at TEXT,
      FOREIGN KEY(uri) REFERENCES posts(uri)
    );

    CREATE INDEX IF NOT EXISTS idx_created_at ON posts(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_hour ON metrics(hour_posted);
  `);

  return db;
}

/**
 * Record a post with engagement metrics
 */
export function recordPost(post: BlueskyPost): void {
  const db = initDB();
  const stmt = db.prepare(`
    INSERT OR REPLACE INTO posts (uri, text, created_at, likes, reposts, replies, fetched_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  stmt.run(post.uri, post.text, post.created_at, post.likes, post.reposts, post.replies, post.fetched_at);

  // Record metrics
  const createdDate = new Date(post.created_at);
  const hour = createdDate.getUTCHours();
  const day = createdDate.toLocaleDateString('en-US', { weekday: 'long' });
  const engagement = (post.likes + post.reposts + post.replies) / Math.max(post.text.length, 1);

  const metricStmt = db.prepare(`
    INSERT INTO metrics (uri, engagement_rate, hour_posted, day_of_week, text_length, recorded_at)
    VALUES (?, ?, ?, ?, ?, ?)
  `);

  metricStmt.run(post.uri, engagement, hour, day, post.text.length, new Date().toISOString());
  db.close();
}

/**
 * Get top performing posts
 */
export function getTopPosts(limit: number = 10): PostMetrics[] {
  const db = initDB();
  const rows = db.prepare(`
    SELECT uri, text, created_at, likes, reposts, replies,
           (likes + reposts + replies) / CAST(MAX(LENGTH(text), 1) AS REAL) as engagement_rate,
           CAST((julianday('now') - julianday(created_at)) * 24 AS INTEGER) as hours_old
    FROM posts
    ORDER BY (likes + reposts + replies) DESC
    LIMIT ?
  `).all(limit) as PostMetrics[];

  db.close();
  return rows;
}

/**
 * Analyze optimal posting times
 */
export function getOptimalPostingTimes(): Record<string, any> {
  const db = initDB();
  const result = db.prepare(`
    SELECT hour_posted, AVG(engagement_rate) as avg_engagement, COUNT(*) as post_count
    FROM metrics
    GROUP BY hour_posted
    ORDER BY avg_engagement DESC
  `).all() as any[];

  db.close();

  return {
    by_hour: result.map(r => ({
      hour: r.hour_posted,
      avg_engagement: r.avg_engagement,
      sample_size: r.post_count
    }))
  };
}

/**
 * Get engagement trends
 */
export function getEngagementTrends(days: number = 7): Record<string, any> {
  const db = initDB();
  const rows = db.prepare(`
    SELECT DATE(created_at) as date, COUNT(*) as post_count, AVG(likes + reposts + replies) as avg_engagement
    FROM posts
    WHERE created_at >= datetime('now', '-' || ? || ' days')
    GROUP BY DATE(created_at)
    ORDER BY date DESC
  `).all(days) as any[];

  db.close();
  return { trends: rows };
}

/**
 * Export analytics as JSON
 */
export function exportAnalytics(): Record<string, any> {
  return {
    top_posts: getTopPosts(5),
    optimal_times: getOptimalPostingTimes(),
    recent_trends: getEngagementTrends(7),
    exported_at: new Date().toISOString()
  };
}
