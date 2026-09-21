from .tool_messages import display_content
"""Offline, escaped side-by-side report and aggregate metrics."""
import html
import json
import os
from pathlib import Path
from .costs import PRICING, branch_cost


def e(value):
    return html.escape(str(value), quote=True)


def fmt(value, seconds=False):
    if value is None:
        return 'Unavailable'
    return f'{value:.3f}s' if seconds else f'{value:,}'


def details(title, value):
    return '<details><summary>' + e(title) + '</summary><pre>' + e(json.dumps(value, ensure_ascii=False, indent=2)) + '</pre></details>'


def branch_html(branch):
    if not branch:
        return '<p>Not started</p>'
    b = branch
    output = ''
    if b.get('status') != 'succeeded':
        output += f'<p class="muted">Status: {e(b.get("status", "Not started"))}</p>'
    if b.get('answer'):
        answer = b['answer']
        if answer.get('truncated'):
            output += '<p class="warning">Output reached the completion limit.</p>'
        output += '<pre class="answer">' + e(answer['text']) + '</pre>'
    if b.get('error'):
        output += '<p class="warning">' + e(b['error']) + '</p>'
    return output


def score_strip(score):
    if not score:
        return ''
    probability = score['noul']
    return (f'<div class="score-strip"><span class="score-value">Relevant <b>{probability:.1%}</b></span>'
            f'<span>Not relevant {1-probability:.1%}</span></div>')


def history_html(record):
    branches = record.get('branches', {})
    curated = branches.get('with_jev', {}).get('curation')
    selected = curated['selected_message_ids'] if curated else None
    positions = {mid: i + 1 for i, mid in enumerate(selected or [])}
    history = record['original_history_messages']
    count = f'{len(selected)} of {len(history)} retained by Jev' if selected is not None else 'Jev selection unavailable'
    output = f'<details class="conversation" open><summary>Conversation history <span class="muted">· {e(count)}</span></summary>'
    output += '<p class="history-help">Shown in original order. Without Jev receives every message; grey messages are removed by Jev. Position labels show the order of retained history in the curated prompt. The current user message below is sent last in both branches. Noul relevance probabilities appear beneath each message.</p>'
    output += '<div class="history-scroll" tabindex="0" role="region" aria-label="Shared completion history">'
    # Include the shared instruction as recorded in the actual completion request.
    for name in ('without_jev', 'with_jev'):
        messages = branches.get(name, {}).get('completion', {}).get('request', {}).get('messages', [])
        if messages:
            if messages[0].get('role') in ('system', 'developer'):
                m = messages[0]
                output += f'<div class="history-message instruction"><div class="message-label">{e(m["role"].title())} · Shared instruction</div><pre>{e(display_content(m))}</pre></div>'
            break
    for i, (mid, message) in enumerate(zip(record['original_history_message_ids'], history)):
        dropped = selected is not None and mid not in positions
        state = 'Removed by Jev' if dropped else (f'Jev position {positions[mid]}' if selected is not None else 'Selection unavailable')
        output += f'<div class="history-message{" removed" if dropped else ""}"><div class="message-label"><span>{i+1} · {e(message["role"].title())} <span class="message-id">{e(mid)}</span></span><span>{e(state)}</span></div>'
        output += score_strip(curated.get("decisions", {}).get(mid)) if curated else ""
        if curated and mid in curated.get('dependency_retained_message_ids', []):
            output += '<small>Retained with its tool call/result group.</small>'
        output += f'<pre>{e(display_content(message))}</pre></div>'
    if not history:
        output += '<p class="muted">No previous conversation messages.</p>'
    return output + '</div></details>'


def render_report(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text())
    records = []
    for cid in manifest['case_ids']:
        path = directory/'cases'/(cid+'.json')
        if path.exists():
            records.append(json.loads(path.read_text()))
    totals = {}
    for name in ['without_jev', 'with_jev']:
        branches = [r.get('branches', {}).get(name) for r in records]
        t = {'started_branches': sum(b is not None for b in branches),
             'succeeded_branches': sum(bool(b and b['status'] == 'succeeded') for b in branches)}
        for field in ['input_tokens', 'output_tokens']:
            values = [b.get('usage', {}).get(field) if b else None for b in branches]
            t[field] = sum(values) if len(values) == len(manifest['case_ids']) and all(v is not None for v in values) else None
            t['observed_' + field] = sum(b.get('usage', {}).get('observed_' + field, 0) for b in branches if b)
        durations = [b.get('duration_seconds') for b in branches if b]
        known = [v for v in durations if v is not None]
        t['observed_end_to_end_seconds'] = sum(known)
        t['mean_recorded_end_to_end_seconds'] = sum(known) / len(known) if known else None
        totals[name] = t
    summary = {'offline': manifest['offline'], 'run_status': manifest['status'],
               'expected_cases': len(manifest['case_ids']), 'saved_cases': len(records),
               'paired_successes': sum(r.get('comparison', {}).get('both_branches_succeeded', False) for r in records),
               'branches': totals,
               'note': 'Observed subtotals are not full costs if usage is missing. Offline values are fixtures, not experimental results.'}
    temp = directory/'summary.json.tmp'
    temp.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    os.replace(temp, directory/'summary.json')
    body = '<header><h1>Answer review</h1><button id="export">Export reviews</button></header>'
    if manifest['offline']:
        body += '<p class="banner">OFFLINE FIXTURE RUN · Synthetic answers, scores and tokens. This preview is not benchmark evidence.</p>'
    body += '<details class="run-details"><summary>Run details & aggregate metrics</summary>'
    body += f'<p>Run: {e(manifest["run_id"])} · {e(manifest["status"])} · {summary["paired_successes"]}/{summary["expected_cases"]} successful pairs</p>'
    body += '<p><a href="manifest.json">Run manifest</a> · <a href="summary.json">Metrics JSON</a> · <a href="benchmark.snapshot.json">Benchmark snapshot</a></p>'
    body += details('Aggregate usage and timing', summary)
    body += details('Cost estimate rates and assumptions', PRICING)
    body += '<p>Preferences and notes save in this browser when local storage is available. Export for durable storage. Answers appear verbatim, without rendering HTML or Markdown.</p></details>'
    body += '<nav aria-label="Case navigation"><button id="previous" hidden>← Previous</button><label for="case-picker">Case</label><select id="case-picker">'
    body += ''.join(f'<option value="{e(r["case_id"])}">{i+1} / {len(records)} · {e(r["title"])}</option>' for i, r in enumerate(records))
    body += '</select><button id="next" hidden>Next →</button></nav><span id="notice" role="status"></span>'
    for i, record in enumerate(records):
        cid = record['case_id']
        body += f'<section class="case" id="{e(cid)}"><p class="eyebrow">Case {i+1} of {len(records)} · {e(record["title"])}</p>'
        body += history_html(record)
        body += '<div class="question"><h2>User message</h2><pre>' + e(record['target_user_message']['content']) + '</pre></div>'
        body += '<div class="pair"><article><h3>Without Jev</h3>' + branch_html(record['branches'].get('without_jev')) + '</article><article><h3>With Jev</h3>' + branch_html(record['branches'].get('with_jev')) + '</article></div>'
        body += f'<div class="review" data-case="{e(cid)}"><label class="verdict">Which answer is better? <select aria-label="Preferred answer"><option value="unreviewed">Choose a verdict…</option><option value="without_jev">Without Jev</option><option value="with_jev">With Jev</option><option value="tie">Tie</option><option value="both_bad">Both inadequate</option><option value="ungradable">Cannot grade</option></select></label><details><summary>Review notes</summary><label>Notes<textarea rows="3" placeholder="What improved, what was lost, and whether the answer is correct"></textarea></label></details></div>'
        body += '<details class="inspection"><summary>Inspect context, metrics & traces</summary>'
        body += f'<p class="muted"><code>{e(cid)}</code> · {e(record["category_id"])} · execution order: {e(" → ".join(record["branch_order"]))} · <a href="cases/{e(cid)}.json">Full result JSON</a></p>'
        body += '<h3>Timing, tokens & estimated cost</h3><div class="table-scroll"><table><thead><tr><th>Metric</th><th>Without Jev</th><th>With Jev</th></tr></thead><tbody>'
        for label, path, seconds in [
            ('End-to-end', ('duration_seconds',), True),
            ('Jev', ('jev', 'duration_seconds'), True),
            ('Completion', ('completion', 'duration_seconds'), True),
            ('OpenAI input tokens', ('completion', 'usage', 'input_tokens'), False),
            ('OpenAI output tokens', ('completion', 'usage', 'output_tokens'), False),
            ('Jev input tokens', ('jev', 'usage', 'input_tokens'), False),
            ('Jev output tokens', ('jev', 'usage', 'output_tokens'), False),
            ('Total branch input tokens', ('usage', 'input_tokens'), False),
            ('Total branch output tokens', ('usage', 'output_tokens'), False),
        ]:
            body += f'<tr><th>{label}</th>'
            for name in ['without_jev', 'with_jev']:
                value = record['branches'].get(name, {})
                for key in path:
                    value = value.get(key) if isinstance(value, dict) else None
                display = '—' if name == 'without_jev' and path[0] == 'jev' else fmt(value, seconds)
                body += f'<td>{display}</td>'
            body += '</tr>'
        costs = {name: branch_cost(record['branches'].get(name), name, manifest['offline'])
                 for name in ('without_jev', 'with_jev')}
        for label, key in [('Completion cost', 'completion'), ('Jev cost', 'jev'), ('Total branch cost', 'total')]:
            body += f'<tr><th>{label} (USD)</th>'
            for name in ('without_jev', 'with_jev'):
                value = costs[name][key]
                display = f'${value:.6f}' if value is not None else ('Offline fixture' if manifest['offline'] else 'Unavailable')
                body += f'<td>{display}</td>'
            body += '</tr>'
        body += '</tbody></table></div>'
        total_cost = [costs[name]['total'] for name in ('without_jev', 'with_jev')]
        if all(value is not None for value in total_cost):
            body += f'<p class="muted">Combined cost of both branches: <b>${sum(total_cost):.6f} USD</b></p>'
        body += '<p class="muted">List-price estimates, including cache writes and reasoning tokens; before credits or taxes. Pricing snapshot: 2026-09-20. <a href="https://developers.openai.com/api/docs/pricing">OpenAI pricing</a> · <a href="https://typesafe.ai/blog/introducing-system-one-models-and-jev">Jev pricing</a></p>'

        plan = record['branches'].get('with_jev', {}).get('chunk_plan')
        if plan:
            body += f'<p class="muted">Jev chunks: {plan["chunk_count"]} · whole messages, no overlap · sizing uses conservative byte budgets, not exact token counts.</p>'
            body += details('Chunk boundaries and request sizing', plan)
        curation = record['branches'].get('with_jev', {}).get('curation')
        if curation:
            body += f'<h3>Jev selection: {curation["retained_message_count"]}/{curation["original_message_count"]} messages retained</h3><p>Order: {e(", ".join(curation["selected_message_ids"]) or "No history retained")}</p>'
            body += details('Policy and whole-message judgments', curation)
            body += '<details><summary>Inspect original messages with judgments and keep/drop decisions</summary>'
            for mid,m in zip(record['original_history_message_ids'], record['original_history_messages']):
                decision = curation.get('decisions', {}).get(mid)
                score = f"relevance {decision['noul']:.1%}" if decision else 'Unavailable'
                selected = mid in curation['selected_message_ids']
                rank = curation['selected_message_ids'].index(mid)+1 if selected else '—'
                body += f'<h4>{e(mid)} · {e(m["role"])} · {e(score)} · {"kept" if selected else "dropped"} · position {rank}</h4><pre>{e(display_content(m))}</pre>'
            body += '</details>'
        else:
            body += details('Original history', list(zip(record['original_history_message_ids'], record['original_history_messages'])))
        body += details('Comparison metrics and combined case usage', {'comparison': record.get('comparison', {}), 'case_usage': record.get('usage'), 'combined_branch_duration_seconds': record.get('combined_branch_duration_seconds')})
        for name, label in [('without_jev', 'Without Jev'), ('with_jev', 'With Jev')]:
            branch = record['branches'].get(name, {})
            body += details(label + ': model, status, usage & raw traces', branch)
        body += '</details></section>'
    # Script is constant, no unescaped source data is embedded in executable JavaScript.
    script = '''<script>
const storageKey = 'jev-benchmark-review:' + location.pathname;
let saved = {}; try { saved = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch (_) {}
const notice = document.getElementById('notice');
const cases = Array.from(document.querySelectorAll('.case'));
const picker = document.getElementById('case-picker');
const previous = document.getElementById('previous'), next = document.getElementById('next');
function showCase(id) {
 const index = Math.max(0, cases.findIndex(section => section.id === id));
 cases.forEach((section, i) => section.hidden = i !== index);
 if (cases.length) picker.value = cases[index].id;
 previous.disabled = index === 0;
 next.disabled = index >= cases.length - 1;
}
function navigate(id) {
 showCase(id);
 if (cases.length) history.replaceState(null, '', '#' + encodeURIComponent(picker.value));
 window.scrollTo({top: 0});
}
previous.hidden = next.hidden = false;
picker.addEventListener('change', () => navigate(picker.value));
previous.addEventListener('click', () => navigate(cases[picker.selectedIndex - 1]?.id));
next.addEventListener('click', () => navigate(cases[picker.selectedIndex + 1]?.id));
function fromHash() {
 let id = ''; try { id = decodeURIComponent(location.hash.slice(1)); } catch (_) {}
 showCase(id);
}
window.addEventListener('hashchange', fromHash);
fromHash();
for (const row of document.querySelectorAll('.review')) {
 const id = row.dataset.case, select = row.querySelector('select'), notes = row.querySelector('textarea');
 if (saved[id]) { select.value = saved[id].preference || 'unreviewed'; notes.value = saved[id].notes || ''; if (notes.value) notes.closest('details').open = true; }
 const change = () => { saved[id] = {preference: select.value, notes: notes.value};
   try { localStorage.setItem(storageKey, JSON.stringify(saved)); notice.textContent = ' Saved in this browser.'; }
   catch (_) { notice.textContent = ' Browser storage unavailable; use Export.'; }
 };
 select.addEventListener('change', change); notes.addEventListener('input', change);
}
document.getElementById('export').addEventListener('click', () => {
 const reviews = Array.from(document.querySelectorAll('.review')).map(row => ({case_id:row.dataset.case, preference:row.querySelector('select').value, notes:row.querySelector('textarea').value}));
 const payload = {run_path:location.pathname, exported_at:new Date().toISOString(), reviews};
 const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'}));
 const link = document.createElement('a'); link.href=url; link.download='manual-reviews.json'; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
});
</script>'''
    css = """
.score-strip{display:flex;align-items:center;gap:18px;flex-wrap:wrap;margin:10px 0 12px;font-size:11px;color:#697068}.score-value{white-space:nowrap}.score-value b{color:#344633;font-size:13px;font-variant-numeric:tabular-nums}.probabilities{display:flex;gap:8px}.probability{width:52px;font-variant-numeric:tabular-nums}.probability>span:first-child{display:flex;justify-content:space-between;gap:6px}.probability b{font-weight:500}.probability-track{display:block;height:3px;margin-top:4px;background:#e2e6df;border-radius:3px;overflow:hidden}.probability-track>span{display:block;height:100%;background:#a5b39d}.probability.peak{color:#344633}.probability.peak b{font-weight:700}.probability.peak .probability-track>span{background:#627d57}.removed .score-value b,.removed .probability.peak{color:#626262}.removed .probability-track>span{background:#aaa}.removed .probability.peak .probability-track>span{background:#777}
.conversation{margin:18px 0 24px;border:1px solid #e1e5df;border-radius:10px;background:#fff;padding:4px 18px 14px}.conversation>summary{font-size:14px}.conversation>summary .muted{font-weight:400}.history-help{font-size:12px;color:#737b70;margin:0 0 14px}.history-scroll{max-height:440px;overflow:auto;overscroll-behavior:contain;padding:0 8px 0 0}.history-message{padding:16px;border-left:3px solid #a7b9a6;background:#fafcf9;border-radius:4px;margin-bottom:10px}.history-message pre{font:14px/1.65 system-ui;background:transparent;padding:0;margin:8px 0 0}.message-label{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12px;font-weight:500;color:#536650}.message-id{font-weight:400;color:#7b8476;margin-left:6px}.history-message.removed{background:#f1f1f1;border-color:#d2d2d2;color:#777}.history-message.removed .message-label,.history-message.removed .message-id{color:#777}.history-message.instruction{background:#fafaf9;border-color:#dedfd8}
*{box-sizing:border-box}body{font:15px/1.6 system-ui,sans-serif;background:#fafaf9;color:#252926;max-width:1280px;margin:32px auto;padding:0 32px 64px}header{display:flex;align-items:center;justify-content:space-between;gap:16px}h1{font-size:22px;font-weight:600;margin:0}h2,h3{font-size:14px;font-weight:600;margin:0 0 12px}a{color:#426756}button,select,textarea{font:inherit;color:inherit;border:1px solid #d9ddd8;border-radius:7px;background:#fff;padding:8px 12px}button{cursor:pointer}button:hover{background:#f0f2ee}button:disabled{opacity:.4;cursor:default}:focus-visible{outline:2px solid #527663;outline-offset:3px}.banner{font-size:12px;color:#746342;margin:12px 0}.run-details{font-size:13px;color:#697068;margin:16px 0 24px}summary{cursor:pointer;padding:10px 0;font-weight:500}details[open]>summary{margin-bottom:12px}nav{display:flex;align-items:center;gap:12px;padding:18px 0;border-top:1px solid #e3e5e0;border-bottom:1px solid #e3e5e0}nav label{color:#72786f;font-size:13px}nav select{flex:1;min-width:0}nav button{white-space:nowrap}#notice{display:block;font-size:12px;color:#72786f;min-height:24px;padding-top:4px}.eyebrow{font-size:12px;color:#777e74;margin:12px 0}.question{margin:20px 0 28px}.question h2{color:#697266}.question pre{font:18px/1.65 system-ui;background:transparent;padding:0;margin:0;max-height:320px;overflow:auto}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{background:white;border:1px solid #e1e5df;border-radius:10px;padding:24px;min-width:0}article h3{padding-bottom:14px;border-bottom:1px solid #eef0ec;color:#687264}.answer{font:15px/1.75 system-ui;background:none;padding:0;margin:0}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 ui-monospace,monospace;background:#f2f3f0;padding:16px;border-radius:6px;max-width:100%}.review{margin:24px 0;padding:20px 0;border-bottom:1px solid #e3e5e0}.verdict{display:flex;align-items:center;gap:20px;font-weight:600}.verdict select{font-weight:400}.review details{font-size:13px;color:#697068;margin-top:8px}textarea{display:block;width:100%;margin-top:8px;resize:vertical}.inspection{font-size:13px;color:#626c60}.inspection>summary{padding:14px 0}.inspection h3{margin-top:20px}.inspection details{border-top:1px solid #e3e5e0}.muted{color:#747c71;font-size:13px}.warning{color:#85511c;background:#fff7e8;padding:12px;border-radius:6px}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;text-align:left;margin-bottom:20px}th,td{padding:9px 12px;border-bottom:1px solid #e3e5e0}th{font-weight:500}td{font-variant-numeric:tabular-nums}[hidden]{display:none!important}@media(max-width:750px){body{padding:0 16px 40px;margin-top:20px}.pair{grid-template-columns:1fr}article{padding:18px}nav{gap:6px;flex-wrap:wrap}nav label{display:none}nav select{order:-1;flex-basis:100%}.verdict{align-items:flex-start;flex-direction:column;gap:8px}.question pre{font-size:16px}}
"""
    doc = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Jev benchmark review</title><style>' + css + '</style><body>' + body + script + '</body></html>'
    temp = directory/'review.html.tmp'
    temp.write_text(doc)
    os.replace(temp, directory/'review.html')
    return summary
