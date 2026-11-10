from __future__ import annotations

import json
import re
from pathlib import Path

PRODUCT='Commerce Business OS'
VERSION='1.0.0-beta.6'
BUILD='TEAM-TEST-006'
SCHEMA='58'

# Active tester/release documents. Historical implementation modules and CHANGELOG
# may legitimately mention older releases when clearly describing history.
ACTIVE_TEXT_FILES=(
    'VERSION',
    'README_FIRST.md',
    'docs/QUICK_START.md',
    'docs/TESTER_GUIDE.md',
    'docs/TEST_CHECKLIST.md',
    'docs/KNOWN_LIMITATIONS.md',
    'docs/RELEASE_NOTES.md',
    'reports/AUDIT_REPORT.md',
    'reports/TEST_RESULTS.md',
    'reports/RELEASE_READINESS.md',
)


def release_root() -> Path:
    return Path(__file__).resolve().parent.parent


def verify_release_identity(root: Path|None=None) -> dict:
    root=(root or release_root()).resolve()
    findings=[]
    expected_tokens=(VERSION,BUILD)
    for rel in ACTIVE_TEXT_FILES:
        path=root/rel
        if not path.is_file():
            findings.append({'file':rel,'problem':'missing'})
            continue
        text=path.read_text(encoding='utf-8',errors='replace')
        for token in expected_tokens:
            if token not in text:
                findings.append({'file':rel,'problem':'missing current release token','expected':token})
        if not re.search(r'(?i)schema.{0,16}58',text):
            findings.append({'file':rel,'problem':'missing current schema','expected':SCHEMA})
        # Current documents must not use an older release as their heading/metadata.
        # Explicit baseline/history narrative is allowed outside the current identity.
        for line in text.splitlines()[:40]:
            low=line.lower()
            if any(word in low for word in ('baseline','previous','historical','history','since prior','from prior')):
                continue
            if re.search(r'1\.0\.0-beta\.[45]|TEAM-TEST-00[45]',line):
                findings.append({'file':rel,'problem':'stale current-release identity','line':line[:300]})
        for m in re.finditer(r'(?i)\bschema\s*[:#-]?\s*\*\*?(\d+)\*\*?',text):
            if m.group(1)!=SCHEMA:
                findings.append({'file':rel,'problem':'schema drift','actual':m.group(1),'expected':SCHEMA})
    version_file=root/'VERSION'
    if version_file.is_file():
        text=version_file.read_text(encoding='utf-8',errors='replace')
        required=(f'Version: {VERSION}',f'Build: {BUILD}',f'Schema: {SCHEMA}')
        for item in required:
            if item not in text:
                findings.append({'file':'VERSION','problem':'metadata mismatch','expected':item})
    return {'ok':not findings,'product':PRODUCT,'version':VERSION,'build':BUILD,'schema':SCHEMA,'findings':findings}


def main() -> int:
    result=verify_release_identity()
    print(json.dumps(result,indent=2))
    return 0 if result['ok'] else 2


if __name__=='__main__':
    raise SystemExit(main())
