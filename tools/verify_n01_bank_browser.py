"""Run committed ALGO UI geometry checks with educational bank fixtures.

All actors/API responses are synthetic; the application listens on loopback.
The already maintained frontend harness tests the real page components.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True,type=Path)
    p.add_argument('--fixtures',required=True,type=Path)
    p.add_argument('--frontend-sha',required=True)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--label',default='bank',help='Label for the local evidence files')
    p.add_argument('--wrap-answer-task-id',action='append',default=[],
                   help='Require this task to fit without horizontal scrolling')
    args=p.parse_args()
    repo=args.workspace/'algo-front'
    sha=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
    assert sha==args.frontend_sha and len(sha)==40
    assert not subprocess.check_output(['git','-C',str(repo),'status','--porcelain'],text=True).strip()
    source=subprocess.check_output(['git','-C',str(repo),'show',sha+':tests/math-layout.browser.cjs'],text=True)
    rows=json.loads(args.fixtures.read_text())
    assert rows and all('question_latex' in r and len(r['answer_options'])==4 for r in rows)
    assert set(args.wrap_answer_task_id)<={r['id'] for r in rows}
    tasks=[{'task_id':r['id'],'question_text':'LEGACY_SOURCE_MUST_NOT_DISPLAY',
            'question_latex':r['question_latex'],'skill_name':'Educational rendering check',
            'difficulty':'medium','answer_type':'choice','options':r['answer_options'],
            'options_latex':r['answer_options_latex'],'correct_answer':r['correct_answer'],
            'correct_answer_latex':r['correct_answer_latex'],'distractor_meta':r['distractor_meta']}
           for r in rows]
    start=source.index('const expressions=[');end=source.index("let selected=0,role='teacher';",start)
    source=source[:start]+'const tasks='+json.dumps(tasks,ensure_ascii=False)+';\n'+source[end:]
    source=source.replace('correct_answer_latex:expressions[1]', 'correct_answer_latex:t.correct_answer_latex')
    old="['diagnostic-integral','diagnostic-root','diagnostic-system','diagnostic-wide','diagnostic-matrix'][selected]"
    assert old in source
    source=source.replace(old,"('diagnostic-'+tasks[selected].task_id)")
    text_only_surfaces=['diagnostic-'+t['task_id'] for t in tasks
                        if not any('$' in value or '\\' in value
                                   for value in [t['question_latex'],*t['options_latex']])]
    start=source.index("  if(label!=='before'){");end=source.index('\n }finally',start)
    wrap_surfaces=['diagnostic-'+i for i in args.wrap_answer_task_id]
    source=source[:start]+'  const textOnlySurfaces='+json.dumps(text_only_surfaces)+';\n'+'  const wrapSurfaces='+json.dumps(wrap_surfaces)+';\n'+'''  assert.equal(result.checks.length,tasks.length*3+15);
  assert.equal(result.pageErrors.length,0,JSON.stringify(result.pageErrors));
  assert.equal(result.unhandledAPI.length,0,JSON.stringify(result.unhandledAPI));
  assert.ok(result.checks.filter(c=>wrapSurfaces.includes(c.surface)).every(c=>c.horizontalScrollers===0),'Numeric answer sequences should wrap between values');
  assert.ok(result.checks.every(c=>c.mathErrors===0&&!c.legacyVisible&&c.renderers>0&&(textOnlySurfaces.includes(c.surface)?c.glyphs===0:c.glyphs>0)&&c.pageWidth<=c.viewport+1&&c.bodyWidth<=c.viewport+1&&c.verticalClipCount===0&&c.rowOverlapCount===0&&!c.rawTeXVisible),'Bank geometry/overflow regression failed');
'''+source[end:]
    source=source.replace('p09-${label}-math-surfaces-2026-10-04.json','n01-${label}-math-surfaces-2026-10-05.json')
    args.output.mkdir(parents=True,exist_ok=True)
    with socket.socket() as check:check.bind(('127.0.0.1',3311))
    script=args.output/'bank-fixture-browser.cjs';script.write_text(source)
    runtime=Path(os.environ['N01_NODE_RUNTIME'])
    env={**os.environ,'QA_BASE':'http://127.0.0.1:3311','QA_LABEL':args.label,
         'QA_OUTPUT':str(args.output),'QA_REVISION':sha}
    with (args.output/'frontend.log').open('w') as log:
        server=subprocess.Popen([str(runtime),str(repo/'node_modules/next/dist/bin/next'),'dev','-H','127.0.0.1','-p','3311'],cwd=repo,stdout=log,stderr=log,env=env)
        try:
            ready=False
            for _ in range(45):
                assert server.poll() is None,'Local frontend exited'
                try:
                    with urllib.request.urlopen(env['QA_BASE'],timeout=2) as response:
                        ready=response.status==200
                    if ready: break
                except Exception: time.sleep(1)
            assert ready,'Local frontend did not start'
            subprocess.run([str(runtime),str(script)],env=env,check=True,timeout=300)
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill();server.wait()


if __name__=='__main__': main()
