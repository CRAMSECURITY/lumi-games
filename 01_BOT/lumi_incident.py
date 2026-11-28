"""Local incident classification; emits sanitized JSON for an external scheduler."""
import argparse
import json
from lumi_observability import probe


def classify(result):
    status = result.get('status')
    if status == 'ok':
        return {'severity': 'none', 'event': 'healthy', 'action': 'none'}
    if status == 'degraded':
        return {'severity': 'warning', 'event': 'database_degraded', 'action': 'inspect_metrics'}
    return {'severity': 'critical', 'event': 'database_unavailable', 'action': 'inspect_database_and_backups'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database')
    parser.add_argument('--slow-ms', type=int, default=500)
    parser.add_argument('--error-limit', type=int, default=20)
    args = parser.parse_args(argv)
    try:
        result = probe(args.database, slow_ms=args.slow_ms, error_limit=args.error_limit)
    except ValueError:
        parser.error('Invalid thresholds')
    event = classify(result)
    print(json.dumps(event, sort_keys=True))
    return {'none': 0, 'warning': 1, 'critical': 2}[event['severity']]


if __name__ == '__main__':
    raise SystemExit(main())
