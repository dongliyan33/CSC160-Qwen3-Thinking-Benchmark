#!/usr/bin/env python3
"""Descriptive summaries from student grades; no answer evaluation."""
import csv
import html
import json
from pathlib import Path
import statistics
import sys
import benchmark as b

ROOT = b.ROOT
locate = b.locate

def load_graded(root):
    if not (locate(root, 'experiment_manifest.json')).exists():
        raise ValueError('No experiment has been executed. Summary requires 30 responses and your manual grades.')
    manifest = b.read(locate(root, 'experiment_manifest.json'))
    for name, digest in manifest['hashes'].items():
        if b.sha(locate(root, 'frozen_inputs')/name) != digest:
            raise ValueError('Frozen experiment input changed: '+name)
    raw = [json.loads(x) for x in (locate(root, 'raw_responses.jsonl')).read_text(encoding='utf-8').splitlines() if x.strip()]
    with (locate(root, 'results.csv')).open(encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    expected = {r['run_id']:r for r in manifest['schedule']}
    if len(raw) != 30 or len(rows) != 30 or len({r['run_id'] for r in raw}) != 30 or len({r['run_id'] for r in rows}) != 30:
        raise ValueError('Exactly 30 unique raw and graded records required.')
    if set(expected) != {r['run_id'] for r in raw} or set(expected) != {r['run_id'] for r in rows}:
        raise ValueError('Run IDs do not match frozen schedule.')
    by_id = {r['run_id']:r for r in raw}
    for row in rows:
        original = by_id[row['run_id']]
        if original['completion_status'] != 'completed':
            raise ValueError('Technical failures or truncated outputs require review; not treated as wrong answers.')
        for k in b.FIELDS:
            if k not in ('grade','grading_notes'):
                val = original.get(k, '')
                if row.get(k,'') != ('' if val is None else str(val)):
                    raise ValueError('Raw data column edited in CSV: '+row['run_id']+' / '+k)
        for k in ('question_id','condition','trial'):
            if str(original[k]) != str(expected[row['run_id']][k]):
                raise ValueError('Record does not match scheduled condition/question/trial.')
        if row['grade'] not in ('0','1','2'):
            raise ValueError('Every response requires a manual grade 0, 1, or 2.')
        if row['answer_type'] == 'binary' and row['grade'] == '1':
            raise ValueError('Binary question requires grade 0 or 2.')
        row['grade'] = int(row['grade'])
        row['response_time_seconds'] = float(row['response_time_seconds'])
        row['output_tokens'] = int(row['output_tokens']) if row['output_tokens'] else None
    return rows, raw, manifest

def metrics(rows):
    grades = [r['grade'] for r in rows]
    times = [r['response_time_seconds'] for r in rows]
    tokens = [r['output_tokens'] for r in rows if r['output_tokens'] is not None]
    return dict(n=len(rows), correct=grades.count(2), accuracy=grades.count(2)/len(rows),
                mean_score=statistics.mean(grades), score_population_sd=statistics.pstdev(grades),
                score_range=max(grades)-min(grades), all_grades_equal=len(set(grades))==1,
                mean_response_seconds=statistics.mean(times), median_response_seconds=statistics.median(times),
                mean_output_tokens=statistics.mean(tokens) if tokens else None,
                output_token_observations=len(tokens))

def table(headers, rows):
    def cell(x):
        return str(x).replace('|','\\|').replace('\n','<br>')
    return '\n'.join(['| '+' | '.join(headers)+' |', '| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(cell(x) for x in row)+' |' for row in rows])

def chart(path, title, series, ymax, unit):
    # Standalone, dependency-free vector chart. All values derive from manual grades/data.
    width, height = 840, 400
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="40" y="36" font-family="Arial" font-size="22">{html.escape(title)}</text>']
    for tick in range(5):
        y=310-tick*55
        parts.append(f'<path d="M80 {y} H800" stroke="#dddddd"/><text x="65" y="{y+5}" text-anchor="end" font-family="Arial" font-size="12">{ymax*tick/4:.1f}</text>')
    for i,(label,value,color) in enumerate(series):
        x=100+i*700/len(series); w=500/len(series); h=value/ymax*220
        parts.append(f'<rect x="{x}" y="{310-h}" width="{w}" height="{h}" fill="{color}"/><text x="{x+w/2}" y="{300-h}" text-anchor="middle" font-family="Arial" font-size="14">{value:.1f}{html.escape(unit)}</text><text x="{x+w/2}" y="340" text-anchor="middle" font-family="Arial" font-size="14">{html.escape(label)}</text>')
    parts.append('</svg>')
    path.write_text('\n'.join(parts), encoding='utf-8')

def replace_section(text, label, content):
    start, end = '<!-- BEGIN '+label+' -->', '<!-- END '+label+' -->'
    if text.count(start)!=1 or text.count(end)!=1:
        raise ValueError('Report template is missing unique markers: '+label)
    left, rest = text.split(start)
    _, right = rest.split(end)
    return left+start+'\n'+content+'\n'+end+right

def main(root=ROOT):
    rows, raw, manifest = load_graded(root)
    groups = {c:metrics([r for r in rows if r['condition']==c]) for c in ('OFF','ON')}
    by_question = []
    for q in ('Q1','Q2','Q3','Q4','Q5'):
        for c in ('OFF','ON'):
            subset = sorted([r for r in rows if r['question_id']==q and r['condition']==c],key=lambda r:int(r['trial']))
            by_question.append(dict(question_id=q, condition=c, grades=[r['grade'] for r in subset], **metrics(subset)))
    delta = 100*(groups['ON']['accuracy']-groups['OFF']['accuracy'])
    out=locate(root, 'summary'); out.mkdir(parents=True, exist_ok=True)
    (out/'figures').mkdir(exist_ok=True)
    b.save(out/'statistics.json', dict(conditions=groups, by_question=by_question,accuracy_difference_percentage_points=delta))
    for filename, data in [('conditions.csv',[dict(condition=k,**v) for k,v in groups.items()]),('by_question.csv',by_question)]:
        with (out/filename).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
    overview=table(['Thinking','Correct / 15','Accuracy','Mean score (0–2)','Mean time (s)','Median time (s)','Mean output tokens'],
                   [[c,f"{m['correct']} / 15",f"{100*m['accuracy']:.1f}%",f"{m['mean_score']:.3f}",f"{m['mean_response_seconds']:.2f}",f"{m['median_response_seconds']:.2f}",f"{m['mean_output_tokens']:.1f}" if m['mean_output_tokens'] is not None else 'Unavailable'] for c,m in groups.items()])
    detail=table(['Question','Thinking','Correct / 3','Accuracy','Trial grades 1, 2, 3','Mean score','Score SD','Score range','Same grade in all trials'],
                 [[m['question_id'],m['condition'],f"{m['correct']} / 3",f"{100*m['accuracy']:.1f}%",', '.join(map(str,m['grades'])),f"{m['mean_score']:.3f}",f"{m['score_population_sd']:.3f}",m['score_range'],m['all_grades_equal']] for m in by_question])
    results=overview+'\n\nAccuracy difference (ON minus OFF): '+f'{delta:.1f} percentage points.\n\n'+detail
    results+='\n\nAccuracy means grade 2 divided by 15 (or by 3 within a question). Partial credit affects mean score only. SD is population standard deviation of the three manual scores; identical scores do not establish identical answer content. Response time includes model loading and HTTP latency. Output tokens use Ollama eval_count and may include thinking tokens; they are not a final-answer-only count. No inferential tests or general causal claims are produced.\n\n![Accuracy](figures/accuracy.svg)\n\n![Mean response time](figures/response_time.svg)'
    chart(out/'figures'/'accuracy.svg','Correct-response accuracy',[(c,100*m['accuracy'],color) for (c,m),color in zip(groups.items(),['#3975ab','#cc702b'])],100,'%')
    max_time=max(m['mean_response_seconds'] for m in groups.values())
    chart(out/'figures'/'response_time.svg','Mean response time (seconds)',[(c,m['mean_response_seconds'],color) for (c,m),color in zip(groups.items(),['#3975ab','#cc702b'])],max(max_time*1.2,1),' s')
    (out/'results.md').write_text(results+'\n',encoding='utf-8')
    print('Descriptive tables and charts saved to results/. No report or interpretation generated.')

if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,KeyError) as exc:
        sys.exit(str(exc))
