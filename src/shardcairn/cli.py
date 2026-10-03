"""Narrow, offline command-line interface with bounded machine output."""
from __future__ import annotations

import argparse
import re
import sys

from .canonical import canonical_bytes, manifest_sha256
from .errors import ShardCairnError
from .exporter import export, write_plan, STDOUT_MAX_BYTES
from .manifest import load_manifest, PlanOptions, VerifyOptions
from .parsing import read_bytes, PLAN_MAX_BYTES
from .planner import plan
from .verifier import verify


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default message may echo an arbitrarily long private token.
        raise ShardCairnError('usage', 'Invalid command arguments; use --help', exit_code=2)


def _integer(text: str) -> int:
    if len(text) > 8 or re.fullmatch(r'0|[1-9][0-9]*', text, re.ASCII) is None:
        raise argparse.ArgumentTypeError('expected a bounded nonnegative integer')
    return int(text)


def _parser() -> _Parser:
    parser = _Parser(prog='shardcairn', allow_abbrev=False, description='Offline setup-aware test shard planning. Does not execute tests.')
    parser.add_argument('--version', action='version', version='shardcairn 0.1.0')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=_Parser)
    command = commands.add_parser('plan', allow_abbrev=False, help='write a verified plan to a new directory')
    command.add_argument('manifest')
    command.add_argument('--out-dir', required=True)
    command.add_argument('--mode', choices=('auto','heuristic','exact'), default='auto')
    command.add_argument('--work-limit', type=_integer, default=5000000)
    command.add_argument('--local-candidates', type=_integer, default=100000)
    command.add_argument('--exact-nodes', type=_integer, default=250000)
    command = commands.add_parser('verify', allow_abbrev=False, help='independently verify supplied manifest and plan files')
    command.add_argument('manifest')
    command.add_argument('plan')
    command.add_argument('--audit-optimal', action='store_true')
    command.add_argument('--audit-visits', type=_integer, default=None)
    command.add_argument('--require-optimal', action='store_true')
    command = commands.add_parser('export', allow_abbrev=False, help='export verified selectors to a new directory')
    command.add_argument('manifest')
    command.add_argument('plan')
    command.add_argument('--out-dir', required=True)
    command.add_argument('--format', choices=('json','pytest-argfile'), default='json')
    return parser


def _safe(text: str, limit: int = 512) -> str:
    return ''.join(character if 32 <= ord(character) <= 126 else '?' for character in str(text))[:limit]


def _diagnostic(error: ShardCairnError) -> None:
    message = f"shardcairn: {_safe(error.code,64)}: {_safe(error.message)}"
    if error.pointer:
        message += ' (' + _safe(error.pointer,256) + ')'
    sys.stderr.write(message[:4095] + '\n')


def _output(data: bytes) -> None:
    if len(data) > STDOUT_MAX_BYTES:
        raise ShardCairnError('output_size_limit', 'Command output exceeds byte limit', exit_code=5)
    binary = getattr(sys.stdout, 'buffer', None)
    if binary is not None:
        binary.write(data)
        binary.flush()
    else:
        # Embedded callers may deliberately replace stdout with StringIO.
        sys.stdout.write(data.decode('ascii'))
        sys.stdout.flush()


def _failed_verification(error: ShardCairnError, args, manifest_hash=None) -> bytes:
    requested = bool(args.audit_optimal)
    return canonical_bytes({'verification_version': 1,
        'result': 'resource_limit' if error.exit_code == 5 else 'invalid',
        'manifest_sha256': manifest_hash, 'plan_sha256': None,
        'checks': {'coverage': None, 'arithmetic': None, 'baseline': None},
        'producer_claim': None, 'optimality': 'unknown',
        'audit': {'state': 'not_run' if requested else 'not_requested', 'assignments_visited': 0,
                  'assignment_limit': (1000000 if args.audit_visits is None else args.audit_visits) if requested else 0,
                  'witness': None},
        'errors': [{'code': _safe(error.code,64), 'pointer': _safe(error.pointer,256), 'message': _safe(error.message)}]})


def main(argv=None) -> int:
    """Return the protocol exit code; __main__ owns process exit."""
    args = None
    manifest_hash = None
    try:
        try:
            args = _parser().parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)
        if args.command == 'verify':
            if args.audit_visits is not None and not args.audit_optimal:
                raise ShardCairnError('usage', '--audit-visits requires --audit-optimal', exit_code=2)
            options = VerifyOptions(audit_optimal=args.audit_optimal,
                                    audit_visits=1000000 if args.audit_visits is None else args.audit_visits,
                                    require_optimal=args.require_optimal)
        elif args.command == 'plan':
            options = PlanOptions(mode=args.mode, work_limit=args.work_limit,
                                  local_candidates=args.local_candidates, exact_nodes=args.exact_nodes)
        manifest = load_manifest(args.manifest)
        manifest_hash = manifest_sha256(manifest)
        if args.command == 'plan':
            result = write_plan(manifest, plan(manifest, options), args.out_dir)
            _output(result.to_bytes())
            return 0
        document = read_bytes(args.plan, PLAN_MAX_BYTES)
        if args.command == 'export':
            _output(export(manifest, document, args.out_dir, args.format).to_bytes())
            return 0
        result = verify(manifest, document, options)
        _output(result.to_bytes())
        if result.exit_code:
            report = result.to_dict()
            errors = report['errors']
            if errors:
                error = errors[0]
                _diagnostic(ShardCairnError(error['code'], error['message'], error['pointer'], result.exit_code))
            else:
                _diagnostic(ShardCairnError('optimality_not_proved', 'Requested independent optimality level was not established', exit_code=result.exit_code))
        return result.exit_code
    except ShardCairnError as error:
        if args is not None and args.command == 'verify' and error.exit_code not in (2,70):
            try:
                _output(_failed_verification(error,args,manifest_hash))
            except (OSError, ShardCairnError):
                _diagnostic(ShardCairnError('output_io','Cannot write command output',exit_code=4))
                return 4
        _diagnostic(error)
        return error.exit_code
    except (OSError, UnicodeError):
        error = ShardCairnError('io_error','Cannot read input or write output',exit_code=4)
        if args is not None and args.command == 'verify':
            try:
                _output(_failed_verification(error,args,manifest_hash))
            except (OSError, ShardCairnError):
                pass
        _diagnostic(error)
        return 4
    except Exception:
        _diagnostic(ShardCairnError('internal_error','Internal invariant failure',exit_code=70))
        return 70
