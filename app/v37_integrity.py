"""V37 integrity + business-readiness gate."""
from pathlib import Path
import v36_integrity
import v37_business_readiness as br


def integrity_gate(root: Path|None=None, record: bool=False) -> dict:
    base=v36_integrity.integrity_gate(record=record);findings=list(base.get('findings',[]))
    if root is not None:findings.extend(br.doctor_findings(root))
    critical=sum(1 for x in findings if x.get('severity')=='Critical')
    high=sum(1 for x in findings if x.get('severity')=='High')
    return {'status':'Broken' if critical else ('Needs attention' if high else 'Working'),'critical':critical,'high':high,'findings':findings}
