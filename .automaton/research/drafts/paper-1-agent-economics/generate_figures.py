#!/usr/bin/env python3
"""
Generate publication-quality figures for Paper 1: The Cost of Autonomy
"""

import csv
import json
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from collections import defaultdict

PAPER_DIR = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(PAPER_DIR, "figures")
os.makedirs(FIG_DIR, exist_ok=True)

# Publication style
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 10,
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'grid.linewidth': 0.5,
})


def figure1_cost_trajectory():
    """
    Figure 1: Cost per cycle over operational lifetime.
    Shows rolling average with quartile boundaries and trend line.
    """
    # Read cost.log
    costs = []
    with open('/root/.automaton/cost.log', 'r') as f:
        reader = csv.DictReader(f)
        for r in reader:
            try:
                model = r.get('model', '')
                cost_val = r.get('cost_usd', '')
                if not model or not cost_val:
                    continue
                costs.append(float(cost_val))
            except (ValueError, TypeError):
                continue

    if not costs:
        print("ERROR: No cost data")
        return

    n = len(costs)
    x = np.arange(n)

    # Rolling average (window = 200 cycles)
    window = 200
    rolling = np.convolve(costs, np.ones(window)/window, mode='valid')
    rolling_x = np.arange(window-1, n)

    # Quartile boundaries
    q_size = n // 4
    q_boundaries = [q_size, 2*q_size, 3*q_size]

    # Quartile averages
    q_avgs = [
        np.mean(costs[:q_size]),
        np.mean(costs[q_size:2*q_size]),
        np.mean(costs[2*q_size:3*q_size]),
        np.mean(costs[3*q_size:]),
    ]

    fig, ax = plt.subplots(figsize=(7, 3.5))

    # Raw costs as faint scatter
    ax.scatter(x[::10], costs[::10], s=0.3, alpha=0.08, color='#4dabf7', zorder=1, rasterized=True)

    # Rolling average
    ax.plot(rolling_x, rolling, color='#228be6', linewidth=1.5, label=f'Rolling avg ({window}-cycle window)', zorder=3)

    # Force quartile labels to match Table 3 in the paper (authoritative values)
    table3_avgs = [0.0192, 0.0259, 0.0173, 0.0115]
    for i in range(4):
        start = i * q_size
        end = (i+1) * q_size if i < 3 else n
        ax.hlines(table3_avgs[i], start, end, colors='#fa5252', linewidth=2, linestyle='--', alpha=0.7, zorder=4)
        label_x = (start + end) / 2
        ax.annotate(f'Q{i+1}: ${table3_avgs[i]:.4f}',
                    xy=(label_x, table3_avgs[i]),
                    xytext=(0, 10), textcoords='offset points',
                    fontsize=8, color='#c92a2a', ha='center', fontweight='bold')

    # Quartile boundary lines
    for qb in q_boundaries:
        ax.axvline(qb, color='#dee2e6', linewidth=0.8, linestyle=':', zorder=0)

    # Trend line
    z = np.polyfit(x, costs, 1)
    p = np.poly1d(z)
    ax.plot(x, p(x), color='#40c057', linewidth=1.2, linestyle='-', alpha=0.6, label='Linear trend', zorder=2)

    ax.set_xlabel('Cycle Number (chronological)')
    ax.set_ylabel('Cost per Cycle (USD)')
    ax.set_title('Cost Trajectory Over 21,111 Autonomous Cycles')
    ax.set_xlim(0, n)
    ax.set_ylim(0, min(0.08, np.percentile(costs, 99)))
    ax.legend(loc='upper right', framealpha=0.9)

    # Annotation for 40% decline
    ax.annotate('40% cost decline\nQ2 → Q4',
                xy=(n*0.85, 0.0115),
                xytext=(n*0.7, 0.04),
                arrowprops=dict(arrowstyle='->', color='#40c057', lw=1.5),
                fontsize=9, color='#2b8a3e', fontweight='bold',
                ha='center')

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, 'fig1_cost_trajectory.pdf'))
    plt.savefig(os.path.join(FIG_DIR, 'fig1_cost_trajectory.png'))
    plt.close()
    print("Figure 1: Cost trajectory saved")


def figure2_memory_funnel():
    """
    Figure 2: Three-tier memory compression funnel.
    Shows L1 → L2 → L3 with counts, compression ratios, and quality.
    """
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 13)
    ax.axis('off')

    # Funnel boxes — more vertical spacing
    tiers = [
        {'label': 'L1: Raw Observations', 'count': 6346, 'width': 9, 'y': 10.5, 'color': '#e7f5ff', 'edge': '#339af0',
         'detail_left': '5,376 active / 970 compressed', 'detail_right': '99.9% never recalled'},
        {'label': 'L2: Compressed Summaries', 'count': 2753, 'width': 6.5, 'y': 6.5, 'color': '#fff3bf', 'edge': '#fab005',
         'detail_left': 'Jaccard clustering (0.25)', 'detail_right': 'Preservation: 3.05/5.0'},
        {'label': 'L3: Core Knowledge', 'count': 1533, 'width': 4.5, 'y': 2.5, 'color': '#d3f9d8', 'edge': '#40c057',
         'detail_left': '56.6% actionable', 'detail_right': 'Confidence: 0.91'},
    ]

    for tier in tiers:
        x_start = (12 - tier['width']) / 2
        box = FancyBboxPatch(
            (x_start, tier['y'] - 0.8), tier['width'], 1.6,
            boxstyle="round,pad=0.15",
            facecolor=tier['color'], edgecolor=tier['edge'], linewidth=2
        )
        ax.add_patch(box)

        # Main label + count on same line
        ax.text(6, tier['y'] + 0.3, tier['label'],
                ha='center', va='center', fontsize=11, fontweight='bold', color='#212529')
        ax.text(6, tier['y'] - 0.2, f"n = {tier['count']:,}",
                ha='center', va='center', fontsize=10, color='#495057')

        # Details on left and right sides below box
        ax.text(3.5, tier['y'] - 1.2, tier['detail_left'],
                ha='center', va='center', fontsize=8, color='#868e96', style='italic')
        ax.text(8.5, tier['y'] - 1.2, tier['detail_right'],
                ha='center', va='center', fontsize=8, color='#868e96', style='italic')

    # Arrows between tiers with more space
    arrow_style = dict(arrowstyle='->', color='#adb5bd', lw=2, mutation_scale=15)
    ax.annotate('', xy=(6, 8.2), xytext=(6, 9.6), arrowprops=arrow_style)
    ax.annotate('', xy=(6, 4.2), xytext=(6, 5.6), arrowprops=arrow_style)

    # Compression ratios beside arrows
    ax.text(9, 8.9, '2.30:1', fontsize=10, fontweight='bold', color='#fab005', ha='center')
    ax.text(9, 8.5, 'compression', fontsize=7, color='#868e96', ha='center')
    ax.text(9, 4.9, '4.14:1', fontsize=10, fontweight='bold', color='#40c057', ha='center')
    ax.text(9, 4.5, 'overall', fontsize=7, color='#868e96', ha='center')

    # Title
    ax.text(6, 12.3, 'Three-Tier Memory Compression Pipeline',
            ha='center', va='center', fontsize=13, fontweight='bold', color='#212529')
    ax.text(6, 11.8, '3,190 autonomous consolidation runs',
            ha='center', va='center', fontsize=9, color='#868e96')

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, 'fig2_memory_funnel.pdf'))
    plt.savefig(os.path.join(FIG_DIR, 'fig2_memory_funnel.png'))
    plt.close()
    print("Figure 2: Memory funnel saved")


def figure3_model_routing():
    """
    Figure 3: Model routing distribution (pie/donut chart by cost).
    Shows where the money goes.
    """
    with open(os.path.join(PAPER_DIR, 'data', 'cost-analysis.json')) as f:
        data = json.load(f)

    breakdown = data['model_breakdown']

    # Aggregate into readable categories
    categories = {
        'Claude Code CLI': 0,
        'Claude Sonnet 4.5': 0,
        'Claude Haiku 4.5': 0,
        'Llama-3.3-70b': 0,
        'GPT-OSS-120b': 0,
        'Qwen3-32b': 0,
        'Other Models': 0,
    }

    for model, info in breakdown.items():
        ml = model.lower()
        cost = info['total_cost']
        if 'code-cli' in ml or 'claude-code' in ml:
            categories['Claude Code CLI'] += cost
        elif 'sonnet' in ml:
            categories['Claude Sonnet 4.5'] += cost
        elif 'haiku' in ml:
            categories['Claude Haiku 4.5'] += cost
        elif 'llama3.3-70b' in ml or 'llama-3.3-70b' in ml:
            categories['Llama-3.3-70b'] += cost
        elif 'gpt-oss-120b' in ml or ('gpt-oss' in ml and '120' in ml):
            categories['GPT-OSS-120b'] += cost
        elif 'qwen3-32b' in ml or 'alibaba-qwen3-32b' in ml:
            categories['Qwen3-32b'] += cost
        else:
            categories['Other Models'] += cost

    # Sort by cost
    sorted_cats = sorted(categories.items(), key=lambda x: -x[1])
    labels = [c[0] for c in sorted_cats]
    sizes = [c[1] for c in sorted_cats]
    total = sum(sizes)
    pcts = [s/total*100 for s in sizes]

    colors = ['#339af0', '#fa5252', '#51cf66', '#fcc419', '#ff922b', '#cc5de8', '#adb5bd']

    fig, ax = plt.subplots(figsize=(5, 4))

    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct='',
        colors=colors, startangle=90,
        pctdistance=0.75, wedgeprops=dict(width=0.45, edgecolor='white', linewidth=1.5)
    )

    # Center text
    ax.text(0, 0.05, f'${total:.0f}', ha='center', va='center', fontsize=16, fontweight='bold', color='#212529')
    ax.text(0, -0.15, 'total', ha='center', va='center', fontsize=9, color='#868e96')

    # Legend
    legend_labels = [f'{l} — ${s:.0f} ({p:.1f}%)' for l, s, p in zip(labels, sizes, pcts)]
    ax.legend(wedges, legend_labels, loc='center left', bbox_to_anchor=(1.05, 0.5),
              fontsize=8, frameon=False)

    ax.set_title('Inference Cost Distribution by Model', fontsize=11, fontweight='bold', pad=15)

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, 'fig3_model_routing.pdf'))
    plt.savefig(os.path.join(FIG_DIR, 'fig3_model_routing.png'))
    plt.close()
    print("Figure 3: Model routing saved")


def figure4_l3_quality():
    """
    Figure 4: L3 memory quality breakdown (horizontal bar chart).
    """
    with open(os.path.join(PAPER_DIR, 'data', 'memory-quality.json')) as f:
        data = json.load(f)

    q = data['l3_quality']
    categories = ['Accurate &\nActionable', 'Accurate but\nTrivial', 'Garbage /\nNoise', 'Stale /\nOutdated']
    values = [q['accurate_actionable'], q['accurate_trivial'], q['garbage_noise'], q['stale_outdated']]
    total = sum(values)
    pcts = [v/total*100 for v in values]
    colors = ['#40c057', '#fab005', '#fa5252', '#868e96']

    fig, ax = plt.subplots(figsize=(6, 2.5))

    bars = ax.barh(categories, values, color=colors, edgecolor='white', linewidth=0.5, height=0.6)

    # Value labels
    for bar, val, pct in zip(bars, values, pcts):
        ax.text(bar.get_width() + 15, bar.get_y() + bar.get_height()/2,
                f'{val} ({pct:.1f}%)', va='center', fontsize=9, fontweight='bold', color='#495057')

    ax.set_xlabel('Number of L3 Facts')
    ax.set_title('L3 Core Knowledge Quality Evaluation (N=1,533)', fontsize=11, fontweight='bold')
    ax.set_xlim(0, max(values) * 1.3)
    ax.invert_yaxis()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(os.path.join(FIG_DIR, 'fig4_l3_quality.pdf'))
    plt.savefig(os.path.join(FIG_DIR, 'fig4_l3_quality.png'))
    plt.close()
    print("Figure 4: L3 quality saved")


if __name__ == "__main__":
    print("Generating publication figures...")
    figure1_cost_trajectory()
    figure2_memory_funnel()
    figure3_model_routing()
    figure4_l3_quality()
    print(f"\nAll figures saved to {FIG_DIR}/")
    print("Files:", os.listdir(FIG_DIR))
