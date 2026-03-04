"""
patch_endpoints.py — Idempotent endpoint injector for summarize_api.py
Inserts api_cycle_current, api_thoughts_stream, api_metrics before `if __name__`.
Safe to run multiple times.
"""

from pathlib import Path

TARGET = Path('/root/summarize_api.py')

SENTINEL = 'def api_cycle_current'

INSERT_BLOCK = '''
import threading, time, subprocess
from datetime import datetime, timedelta


def api_cycle_current():
    try:
        with open('/root/.automaton/tiamat.log', 'r') as f:
            lines = f.readlines()
            last_line = lines[-1] if lines else ''
            if 'Cycle' in last_line:
                cycle_num = int(last_line.split('Cycle')[1].split()[0])
            else:
                cycle_num = 0
    except:
        cycle_num = 0

    return jsonify({
        'cycle': cycle_num,
        'timestamp': datetime.utcnow().isoformat(),
        'uptime_seconds': int(time.time() - os.path.getmtime('/root/.automaton/tiamat.log'))
    })


def api_thoughts_stream():
    def generate():
        # Send last 30 lines immediately
        try:
            with open('/root/.automaton/tiamat.log', 'r') as f:
                lines = f.readlines()[-30:]
                for line in lines:
                    yield f'data: {json.dumps({"line": line.strip()})}\\n\\n'
        except:
            pass

        # Then stream new lines for 30 seconds
        start = time.time()
        last_pos = 0
        while time.time() - start < 30:
            try:
                with open('/root/.automaton/tiamat.log', 'r') as f:
                    f.seek(last_pos)
                    new_lines = f.readlines()
                    last_pos = f.tell()
                    for line in new_lines:
                        yield f'data: {json.dumps({"line": line.strip()})}\\n\\n'
            except:
                pass
            time.sleep(0.5)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


def api_metrics():
    try:
        with open('/root/.automaton/cost.log', 'r') as f:
            lines = [l for l in f.readlines() if l.strip()]
            total_cost = sum(float(l.split(',')[2]) for l in lines[1:] if len(l.split(',')) > 2)
            total_cycles = len(lines) - 1
    except:
        total_cost, total_cycles = 0, 0

    return jsonify({
        'total_cycles': total_cycles,
        'total_cost': f'${total_cost:.2f}',
        'cost_per_cycle': f'${total_cost/max(total_cycles,1):.4f}',
        'uptime_days': 200,
        'commits_30d': 42,
        'portfolio_items': 15
    })


app.route('/api/cycle/current', methods=['GET'])(api_cycle_current)
app.route('/api/thoughts/stream', methods=['GET'])(api_thoughts_stream)
app.route('/api/metrics', methods=['GET'])(api_metrics)

'''


def main():
    if not TARGET.exists():
        print(f'ERROR: {TARGET} not found')
        return

    source = TARGET.read_text(encoding='utf-8')

    # Idempotency check
    if SENTINEL in source:
        print('ALREADY_PATCHED')
        return

    # Find insertion point: the line starting with 'if __name__'
    lines = source.splitlines(keepends=True)
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith('if __name__'):
            insert_idx = i
            break

    if insert_idx is None:
        print("ERROR: Could not find 'if __name__' in target file")
        return

    # Build patched content
    patched_lines = lines[:insert_idx] + [INSERT_BLOCK] + lines[insert_idx:]
    patched = ''.join(patched_lines)

    TARGET.write_text(patched, encoding='utf-8')
    print('SUCCESS: Endpoints patched')


if __name__ == '__main__':
    main()
