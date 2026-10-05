"""Check educational bank repairs through actual exam grading/report helpers."""
import argparse
import importlib
import json
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',required=True,type=Path)
    p.add_argument('--manifest',required=True,type=Path)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    source=json.loads(args.source.read_text())
    assert source['student_data_exported'] is False
    rows={r['id']:r for r in source['content']['tasks']}
    manifest=json.loads(args.manifest.read_text())
    sys.path.insert(0,str(args.workspace/'exam-service'))
    checker=importlib.import_module('src.domain.answer_check').check_answer
    fallback=importlib.import_module('src.domain.answer_utils').check_answer
    reports=importlib.import_module('src.domain.distractor_utils')
    graded=0; errors=0
    for entry in manifest['repairs']:
        row={**rows[entry['id']],**entry['changes']}
        key=row['correct_answer']
        for value in row['answer_options']:
            expected=value==key
            assert checker(value,key,row['answer_type'])==expected,(row['id'],value)
            assert fallback(value,key)==expected,(row['id'],value)
            graded+=2
        for distractor in row['distractor_meta']:
            matched=reports.match_distractor(distractor['value'],row['distractor_meta'])
            assert matched==distractor
            assert reports.distractor_text(matched)==distractor['error_logic_latex']
            assert reports.distractor_latex_text(matched)==distractor['error_logic_latex']
            errors+=1
    result={'batch':manifest['batch'],'tasks':len(manifest['repairs']),
            'grading_checks':graded,'report_errors':errors,'offline':True,
            'student_data_included':False,'sessions_created':0}
    rendered=json.dumps(result,indent=2)+'\n'
    if args.output:args.output.write_text(rendered)
    print(rendered)


if __name__=='__main__':main()
