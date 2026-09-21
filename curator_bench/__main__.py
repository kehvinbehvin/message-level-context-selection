import argparse
import json
import sys
from pathlib import Path
from .core import config_from_file, load_benchmark, validate_config
from .report import render_report
from .runtime import run


def main():
    parser = argparse.ArgumentParser(description='Paired full-history versus Jev-selected context benchmark.')
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('validate', help='Validate benchmark and configuration without requests or keys.')
    p.add_argument('--config', default='configs/example.json')
    p = commands.add_parser('run', help='Create an incremental paired run; --offline uses fixtures only.')
    p.add_argument('--config', default='configs/example.json')
    p.add_argument('--output', required=True)
    p.add_argument('--offline', action='store_true')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--model')
    p.add_argument('--case', action='append', default=[], help='Case ID; may be repeated.')
    p = commands.add_parser('report', help='Rebuild HTML and metrics from saved results, no API calls.')
    p.add_argument('directory')
    args = parser.parse_args()
    try:
        if args.command == 'report':
            summary = render_report(Path(args.directory))
            print(json.dumps(summary, indent=2))
            return 0
        config = config_from_file(args.config)
        if getattr(args, 'model', None):
            config['model'] = args.model
        if getattr(args, 'case', None):
            config['case_ids'] = args.case
        validate_config(config, offline=args.command == 'validate' or args.offline)
        benchmark, cases = load_benchmark(config['benchmark'], config['case_ids'])
        if args.command == 'validate':
            print(f'Valid benchmark: {len(cases)} selected cases. No network calls or credentials required.')
            if not config['model']:
                print('Main model remains unset; choose it before a live run.')
            return 0
        manifest = run(config, benchmark, cases, args.output, offline=args.offline, resume=args.resume)
        print(f'Report: {Path(args.output).resolve() / "review.html"}')
        return 0 if manifest['status'] == 'completed' else 1
    except KeyboardInterrupt:
        print('Interrupted. Saved requests/results are retained; resume never automatically replays an in-flight request.', file=sys.stderr)
        return 130
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
