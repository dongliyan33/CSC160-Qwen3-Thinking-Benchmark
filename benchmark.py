#!/usr/bin/env python3
"""Independent Ollama trials. No generation unless run --approve is supplied."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import statistics
import sys
import time
from datetime import datetime, timezone
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parent
FILE_PATHS = {'questions.json': 'config/questions.json', 'reference_answers.json': 'config/reference_answers.json', 'model_configuration.json': 'config/model_configuration.json', 'predictions.md': 'config/predictions.md', 'results.csv': 'data/results.csv', 'raw_responses.jsonl': 'data/raw_responses.jsonl', 'experiment_manifest.json': 'data/experiment_manifest.json', 'experiment.lock': 'data/experiment.lock', 'request_journal.jsonl': 'data/request_journal.jsonl', 'execution_status.json': 'data/execution_status.json', 'phase2_validation.json': 'data/phase2_validation.json', 'frozen_inputs': 'data/frozen_inputs', 'report_template.md': 'report/report_template.md', 'report_populated.md': 'report/report_populated.md', 'summary': 'results', 'benchmark.py': 'benchmark.py', 'summarize_results.py': 'summarize_results.py'}

def locate(root, name):
    return root / FILE_PATHS.get(name, name)

MODEL = 'qwen3:8b'
EXPECTED_ID = '500a1f067a9f'
ENDPOINT = 'http://localhost:11434'
ORDER_SEED = 1602026
OPTIONS = dict(temperature=0.6, top_k=20, top_p=0.95, repeat_penalty=1,
               num_ctx=40960, num_predict=32768, seed=-1)
INSTRUCTION = 'Answer the following mathematical question. Provide a concise final answer. If numerical values are requested, give the values clearly. If the question asks for a Yes/No determination, state Yes or No.'
CATEGORIES = ['Algebra', "Newton's Method", 'Bisection Method', 'Linear Equations', 'Matrix Stability']
FIELDS = ['run_id','execution_index','question_id','category','answer_type','condition','trial',
          'prompt','final_response','thinking_content','model','model_id','model_digest',
          'ollama_version','temperature','top_k','top_p','repeat_penalty','num_ctx','num_predict',
          'sampling_seed','order_seed','think','timestamp','response_time_seconds','input_tokens',
          'output_tokens','done_reason','completion_status','truncated','api_error',
          'observed_context_length','load_duration_ns','grade','grading_notes']

def now():
    return datetime.now(timezone.utc).isoformat()

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    temp.replace(path)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def api(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    req = Request(ENDPOINT+path, data=body, headers={'Content-Type':'application/json'})
    # Never use a configured network proxy for this local experiment.
    with build_opener(ProxyHandler({})).open(req, timeout=3600 if path == '/api/chat' else 20) as res:
        raw = res.read().decode('utf-8')
    return json.loads(raw), raw

def verify_model():
    tags, _ = api('/api/tags')
    model = next((m for m in tags['models'] if m.get('name') == MODEL), None)
    if not model or not model['digest'].removeprefix('sha256:').startswith(EXPECTED_ID):
        raise ValueError('Exact qwen3:8b model ID not installed; no substitution allowed.')
    show, _ = api('/api/show', {'model': MODEL})
    if 'thinking' not in show.get('capabilities', []):
        raise ValueError('Model does not report thinking support.')
    details = show.get('details', {})
    if details.get('family') != 'qwen3' or details.get('quantization_level') != 'Q4_K_M':
        raise ValueError('Unexpected architecture or quantization.')
    version, _ = api('/api/version')
    return dict(verified_at=now(), model=model, show=show, server_version=version)

def questions(root=ROOT):
    data = read(locate(root, 'questions.json'))
    qs = data['questions']
    if data.get('approved_for_experiment') is not True or len(qs) != 5:
        raise ValueError('Five questions must be approved for the experiment first.')
    for i, q in enumerate(qs):
        if q['id'] != 'Q'+str(i+1) or q['category'] != CATEGORIES[i]:
            raise ValueError('Question IDs/categories must match the five slots.')
        if not isinstance(q['question'], str) or not q['question'].strip() or 'TODO' in q['question']:
            raise ValueError('Each question must contain nonempty question text.')
        if q['answer_type'] != ('binary' if i == 4 else 'numerical'):
            raise ValueError('Unexpected answer type.')
        if len(q['question'].encode('utf-8')) > 4000:
            raise ValueError('Question exceeds conservative input budget of 4000 UTF-8 bytes.')
    return qs

def validate(root=ROOT):
    qs = questions(root)
    pred = (locate(root, 'predictions.md')).read_text(encoding='utf-8')
    if 'Predictions complete: YES' not in pred or 'TODO' in pred:
        raise ValueError('Complete every predictions section and change completion marker to YES.')
    config = read(locate(root, 'model_configuration.json'))
    if config['model'] != MODEL or config['explicit_request_options'] != OPTIONS:
        raise ValueError('Configuration does not match the fixed experiment settings.')
    # Deliberately never open reference_answers.json in this program.
    return qs

def schedule(qs):
    plan = [dict(run_id=f"{q['id']}_{'ON' if think else 'OFF'}_{trial}",
                 question_id=q['id'], category=q['category'], answer_type=q['answer_type'],
                 question=q['question'], condition='ON' if think else 'OFF',
                 think=think, trial=trial)
            for q in qs for think in (False, True) for trial in range(1,4)]
    random.Random(ORDER_SEED).shuffle(plan)
    return [dict(item, execution_index=i) for i,item in enumerate(plan,1)]

def payload(item):
    return dict(model=MODEL, messages=[{'role':'user','content':INSTRUCTION+'\n\n'+item['question']}],
                think=item['think'], stream=False, options=OPTIONS.copy(), keep_alive='30m')

def append(path, obj):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, ensure_ascii=False)+'\n')
        f.flush()
        os.fsync(f.fileno())

def export(root=ROOT):
    target = locate(root, 'results.csv')
    prior = {}
    if target.exists():
        with target.open(encoding='utf-8', newline='') as f:
            prior = {r['run_id']:r for r in csv.DictReader(f)}
    records = [json.loads(line) for line in (locate(root, 'raw_responses.jsonl')).read_text(encoding='utf-8').splitlines() if line.strip()]
    temp = target.with_suffix('.csv.tmp')
    with temp.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for record in records:
            record = dict(record)
            record.update({k:prior.get(record['run_id'],{}).get(k,'') for k in ('grade','grading_notes')})
            writer.writerow(record)
    temp.replace(target)

def classify(response, think):
    message = response.get('message', {})
    truncated = response.get('done_reason') == 'length' or response.get('eval_count', 0) >= OPTIONS['num_predict']
    if truncated:
        return 'truncated', True
    if response.get('error'):
        return 'api_error', None
    if response.get('done') is not True or response.get('done_reason') != 'stop':
        return 'incomplete', None
    if not message.get('content', '').strip():
        return 'empty_final_answer', False
    if message.get('tool_calls') or (not think and message.get('thinking')):
        return 'protocol_error', False
    return 'completed', False

def run(root=ROOT):
    qs = validate(root)
    if (locate(root, 'experiment_manifest.json')).exists() or (locate(root, 'raw_responses.jsonl')).stat().st_size:
        raise ValueError('Experiment already started. Never overwrite or automatically retry it.')
    verified = verify_model()
    config = read(locate(root, 'model_configuration.json'))
    if verified['model']['digest'] != config['actual_model_digest']:
        raise ValueError('Model digest changed since preparation.')
    if verified['server_version'] != config['server_version']:
        raise ValueError('Ollama version changed since preparation; review before execution.')
    plan = schedule(qs)
    lock = locate(root, 'experiment.lock')
    with lock.open('x') as f:
        f.write(now())
    # A lock deliberately persists after crashes, preventing accidental duplicate inference.
    try:
        frozen = locate(root, 'frozen_inputs')
        frozen.mkdir()
        for name in ('questions.json','predictions.md','model_configuration.json','benchmark.py','summarize_results.py'):
            (frozen/name).write_bytes(locate(root, name).read_bytes())
            (frozen/name).chmod(0o444)
        manifest = dict(started_at=now(), order_seed=ORDER_SEED, schedule=plan,
                        options=OPTIONS, keep_alive='30m', instruction=INSTRUCTION,
                        hashes={p.name:sha(p) for p in frozen.iterdir()}, verification=verified,
                        retry_policy='No automatic retries. A technical recovery requires a documented decision.')
        save(locate(root, 'experiment_manifest.json'), manifest)
        for item in plan:
            req = payload(item)
            rec = {k:item[k] for k in ('run_id','execution_index','question_id','category','answer_type','condition','trial','think')}
            rec.update(prompt=req['messages'][0]['content'], model=MODEL, model_id=EXPECTED_ID,
                       model_digest=verified['model']['digest'], ollama_version=verified['server_version']['version'],
                       **OPTIONS, sampling_seed=OPTIONS['seed'], order_seed=ORDER_SEED, grade='', grading_notes='',
                       timestamp=now(), request=req, final_response='', thinking_content='', truncated=None,
                       completion_status='api_error', api_error='')
            append(locate(root, 'request_journal.jsonl'), dict(run_id=item['run_id'], timestamp=rec['timestamp'], request=req))
            start = time.perf_counter()
            try:
                current, _ = api('/api/tags')
                if not any(m.get('name') == MODEL and m.get('digest') == rec['model_digest'] for m in current['models']):
                    raise ValueError('Model changed during experiment.')
                start = time.perf_counter()
                response, raw = api('/api/chat', req)
                rec['response_time_seconds'] = time.perf_counter()-start
                rec['raw_api_response_text'] = raw
                rec['api_response'] = response
                rec['final_response'] = response.get('message',{}).get('content','')
                rec['thinking_content'] = response.get('message',{}).get('thinking','')
                rec['input_tokens'] = response.get('prompt_eval_count')
                rec['output_tokens'] = response.get('eval_count')
                rec['load_duration_ns'] = response.get('load_duration')
                rec['done_reason'] = response.get('done_reason')
                rec['completion_status'], rec['truncated'] = classify(response, item['think'])
                rec['api_error'] = response.get('error', '')
                try:
                    running, _ = api('/api/ps')
                    rec['running_models_after_response'] = running
                    loaded = next((m for m in running['models'] if m.get('digest') == rec['model_digest']), {})
                    rec['observed_context_length'] = loaded.get('context_length')
                    if loaded.get('context_length') not in (None, OPTIONS['num_ctx']):
                        rec['completion_status'] = 'protocol_error'
                        rec['api_error'] = 'Observed context differs from requested context.'
                except Exception as exc:
                    rec['metadata_observation_error'] = repr(exc)
            except Exception as exc:
                rec['response_time_seconds'] = time.perf_counter()-start
                rec['api_error'] = repr(exc)
                if hasattr(exc, 'read'):
                    rec['raw_error_body'] = exc.read().decode('utf-8', errors='replace')
            append(locate(root, 'raw_responses.jsonl'), rec)
            export(root)
            print(item['run_id'], rec['completion_status'], flush=True)
        rows = [json.loads(x) for x in (locate(root, 'raw_responses.jsonl')).read_text().splitlines()]
        complete = len(rows) == 30 and all(r['completion_status'] == 'completed' for r in rows)
        save(locate(root, 'execution_status.json'), dict(finished_at=now(), attempted=len(rows),
             completed=sum(r['completion_status']=='completed' for r in rows),
             all_30_successful=complete, no_automatic_retries=True))
        if not complete:
            raise ValueError('Experiment contains technical failures/truncations. Inspect records; no retries made.')
    finally:
        # Keep lock even on completion: accidental reruns must fail closed.
        pass

def initialize(root=ROOT):
    """Prepare private local inputs without API calls or overwriting files."""
    for directory in ('data', 'results/figures'):
        (root/directory).mkdir(parents=True, exist_ok=True)
    target = locate(root, 'questions.json')
    if not target.exists():
        with target.open('x', encoding='utf-8') as f:
            f.write((root/'config'/'questions.example.json').read_text(encoding='utf-8'))
    target = locate(root, 'predictions.md')
    if not target.exists():
        with target.open('x', encoding='utf-8') as f:
            f.write('# Pre-experiment predictions\n\nPredictions complete: NO\n\nTODO: Write your predictions and reasoning about accuracy, repeated-run consistency, and response time before testing.\n')
    target = locate(root, 'raw_responses.jsonl')
    if not target.exists():
        with target.open('x', encoding='utf-8'): pass
    if not locate(root, 'results.csv').exists():
        export(root)
    print('Local files prepared without inference; existing files preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init','plan','validate','verify','run','export'])
    parser.add_argument('--approve', action='store_true', help='Student explicitly approves finalized questions and execution')
    args = parser.parse_args()
    if args.command == 'init':
        initialize()
    elif args.command == 'plan':
        print(json.dumps(schedule(questions()), indent=2))
    elif args.command == 'validate':
        validate(); print('Inputs ready; no API calls made.')
    elif args.command == 'verify':
        print(json.dumps(verify_model(), indent=2))
    elif args.command == 'export':
        export(); print('CSV rebuilt; existing manual grades preserved.')
    elif not args.approve:
        parser.error('Execution requires explicit student approval: run --approve')
    else:
        run()

if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        sys.exit(str(exc))
