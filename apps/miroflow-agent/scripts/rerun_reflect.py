#!/usr/bin/env python3
"""Re-run reflection on existing path logs."""
import asyncio, json, glob, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.evolving.reflector import reflect_on_task, _reflect_comparison
from src.evolving.experience_store import ExperienceStore
from openai import AsyncOpenAI

log_dir = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'futurex_l4_10_multipath_test')
exp_file = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'data', 'experiences.jsonl')

client = AsyncOpenAI(
    api_key=os.environ['OPENAI_API_KEY'],
    base_url='https://openrouter.ai/api/v1'
)
store = ExperienceStore(exp_file)
model = 'openai/gpt-5-2025-08-07'

async def main():
    path_logs = sorted(glob.glob(os.path.join(log_dir, 'task_*_path*_*.json')))
    master_logs = sorted(glob.glob(os.path.join(log_dir, 'task_*_multipath_*.json')))
    print(f'Found {len(path_logs)} path logs, {len(master_logs)} master logs', flush=True)

    # Phase 1: Individual path reflection
    s, f = 0, 0
    for pp in path_logs:
        with open(pp) as fh:
            plog = json.load(fh)
        tid = plog.get('task_id', '?')
        gt = plog.get('ground_truth', '')
        ans = plog.get('final_boxed_answer', '')
        if not gt or not ans:
            f += 1
            print(f'  SKIP {tid[-45:]}: no GT or answer', flush=True)
            continue
        try:
            exp = await reflect_on_task(plog, str(gt), client, model, store)
            if exp:
                s += 1
                print(f'  OK {tid[-45:]}: {exp.get("failure_pattern", "?")}', flush=True)
            else:
                f += 1
                print(f'  EMPTY {tid[-45:]}', flush=True)
        except Exception as e:
            f += 1
            print(f'  ERR {tid[-45:]}: {e}', flush=True)

    print(f'\nPhase 1: {s} ok, {f} fail', flush=True)

    # Phase 2: Cross-path comparison
    cs, cf = 0, 0
    for mp in master_logs:
        with open(mp) as fh:
            mlog = json.load(fh)
        tid = mlog.get('task_id', '?')
        gt = mlog.get('ground_truth', '')
        desc = mlog.get('input', {}).get('task_description', '')
        tid_base = tid.split('_attempt')[0]
        paths = [p for p in path_logs if tid_base in p]
        pr = []
        for p in paths:
            with open(p) as fh:
                pl = json.load(fh)
            pr.append({
                'strategy_name': pl.get('task_id', '').split('_')[-1],
                'answer': pl.get('final_boxed_answer', ''),
                'status': pl.get('status', 'failed'),
                'summary': pl.get('final_summary', '')[:500],
            })
        if not pr:
            continue
        try:
            comp = await _reflect_comparison(pr, desc, str(gt), client, model)
            if comp:
                store.add(comp)
                cs += 1
                print(f'  OK comp {tid[-30:]}: winner={comp.get("winning_strategy", "?")}', flush=True)
            else:
                cf += 1
                print(f'  EMPTY comp {tid[-30:]}', flush=True)
        except Exception as e:
            cf += 1
            print(f'  ERR comp {tid[-30:]}: {e}', flush=True)

    print(f'\nPhase 2: {cs} ok, {cf} fail', flush=True)
    print(f'Total experiences saved to {exp_file}', flush=True)

asyncio.run(main())
