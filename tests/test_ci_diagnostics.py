"""Keep compiler failures visible in CI annotations, including older Swift output."""
import json
import re
from pathlib import Path

import pytest


@pytest.mark.parametrize(('diagnostic', 'severity', 'line', 'column'), [
    ('/Users/runner/work/tscribe/tscribe/macos/Sources/TscribeMac/AppModel.swift:61:27: error: reference to captured var self in concurrently-executing code', 'error', '61', '27'),
    ('/Users/runner/work/tscribe/tscribe/macos/Sources/TscribeMac/WorkerClient.swift:45:33: warning: reference to captured var self in concurrently-executing code; this is an error in Swift 6', 'warning', '45', '33'),
])
def test_swift_matcher_catches_real_ci_diagnostic_format(diagnostic, severity, line, column):
    matcher = json.loads((Path(__file__).parents[1] / '.github/swift-problem-matcher.json').read_text())
    pattern = matcher['problemMatcher'][0]['pattern'][0]
    match = re.match(pattern['regexp'], diagnostic)
    assert match is not None
    assert match.group(pattern['file']).endswith('.swift')
    assert match.group(pattern['severity']) == severity
    assert match.group(pattern['line']) == line
    assert match.group(pattern['column']) == column
    assert match.group(pattern['message']).startswith('reference to captured var')
