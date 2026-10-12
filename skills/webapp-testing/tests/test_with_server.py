#!/usr/bin/env python3
"""Unit tests for with_server.py."""

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import with_server


def test_is_server_ready_success():
    """Test is_server_ready returns True when port is open."""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(('localhost', 0))
    port = server_socket.getsockname()[1]
    server_socket.listen(1)

    def accept_loop():
        try:
            server_socket.settimeout(2.0)
            conn, _ = server_socket.accept()
            conn.close()
        except socket.timeout:
            pass

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()

    try:
        time.sleep(0.1)
        result = with_server.is_server_ready(port, timeout=5)
        assert result is True
    finally:
        server_socket.close()
        thread.join(timeout=1)


def test_is_server_ready_failure():
    """Test is_server_ready returns False when port is closed."""
    result = with_server.is_server_ready(54321, timeout=1)
    assert result is False


def test_is_server_ready_timeout():
    """Test is_server_ready respects timeout."""
    start = time.time()
    result = with_server.is_server_ready(54321, timeout=2)
    elapsed = time.time() - start
    assert result is False
    assert 1.5 < elapsed < 3.0


def _run_main_with_patches(argv, is_server_ready_return_value=None, run_return_value=None,
                           wait_side_effect=None, popen_side_effect=None):
    """Helper to run main with mocked dependencies."""
    from io import StringIO
    from unittest.mock import patch, MagicMock

    # Create mock process(es)
    if popen_side_effect:
        mock_processes = popen_side_effect
    else:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_process.wait.return_value = 0
        if wait_side_effect:
            mock_process.wait.side_effect = wait_side_effect
        mock_processes = [mock_process]

    old_argv = sys.argv[:]
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()

    # Patch is_server_ready in main's globals directly
    original_is_server_ready = with_server.main.__globals__['is_server_ready']
    mock_is_server_ready = MagicMock()
    if is_server_ready_return_value is not None:
        mock_is_server_ready.return_value = is_server_ready_return_value
    else:
        mock_is_server_ready.return_value = True
    with_server.main.__globals__['is_server_ready'] = mock_is_server_ready

    try:
        sys.argv = argv
        with patch('with_server.subprocess.Popen') as mock_popen:
            mock_popen.side_effect = mock_processes

            with patch('with_server.subprocess.run') as mock_run:
                mock_run.return_value = run_return_value or MagicMock(returncode=0)
                try:
                    with_server.main()
                    exit_code = 0
                except SystemExit as e:
                    exit_code = e.code
                except RuntimeError:
                    exit_code = 1
        return exit_code, sys.stdout.getvalue(), mock_popen, mock_processes, mock_run, mock_is_server_ready
    finally:
        # Restore original function
        with_server.main.__globals__['is_server_ready'] = original_is_server_ready
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_main_mismatched_servers_ports():
    """Test main exits with error when server and port counts don't match."""
    exit_code, output, _, _, _, _ = _run_main_with_patches(
        ["with_server.py", "--server", "cmd1", "--server", "cmd2", "--port", "3000", "--", "echo", "test"]
    )
    assert exit_code == 1
    assert "must match" in output


def test_main_no_command():
    """Test main exits with error when no command is specified."""
    exit_code, output, _, _, _, _ = _run_main_with_patches(
        ["with_server.py", "--server", "echo hello", "--port", "3000"]
    )
    assert exit_code == 1
    assert "No command specified" in output


def test_main_single_server_success():
    """Test main runs command successfully with a single mocked server."""
    from unittest.mock import MagicMock
    exit_code, _, mock_popen, mock_processes, mock_run, _ = _run_main_with_patches(
        ["with_server.py", "--server", "sleep 10", "--port", "9999", "--", "echo", "hello"],
        is_server_ready_return_value=True,
        run_return_value=MagicMock(returncode=0),
    )
    assert exit_code == 0
    mock_popen.assert_called_once()
    call_args = mock_popen.call_args
    assert call_args[0][0] == "sleep 10"
    assert call_args[1]['shell'] is True
    mock_run.assert_called_once()
    run_args = mock_run.call_args[0][0]
    assert run_args == ["echo", "hello"]
    # Verify cleanup
    mock_processes[0].terminate.assert_called_once()


def test_main_multiple_servers_success():
    """Test main runs command successfully with multiple mocked servers."""
    from unittest.mock import MagicMock
    mock_process1 = MagicMock()
    mock_process1.poll.return_value = None
    mock_process1.wait.return_value = 0

    mock_process2 = MagicMock()
    mock_process2.poll.return_value = None
    mock_process2.wait.return_value = 0

    exit_code, _, mock_popen, mock_processes, _, _ = _run_main_with_patches(
        [
            "with_server.py",
            "--server", "cmd1", "--port", "3000",
            "--server", "cmd2", "--port", "3001",
            "--", "echo", "test"
        ],
        is_server_ready_return_value=True,
        run_return_value=MagicMock(returncode=0),
        popen_side_effect=[mock_process1, mock_process2],
    )
    assert exit_code == 0
    assert mock_popen.call_count == 2
    mock_process1.terminate.assert_called_once()
    mock_process2.terminate.assert_called_once()


def test_main_server_fails_to_start():
    """Test main exits with error when server fails to start."""
    from unittest.mock import MagicMock
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = 0

    exit_code, _, _, mock_processes, _, _ = _run_main_with_patches(
        ["with_server.py", "--server", "bad_cmd", "--port", "9999", "--", "echo", "test"],
        is_server_ready_return_value=False,
        run_return_value=MagicMock(returncode=0),
        popen_side_effect=[mock_process],
    )
    assert exit_code == 1
    mock_process.terminate.assert_called_once()


def test_main_server_terminate_timeout():
    """Test main kills server when terminate times out."""
    from unittest.mock import MagicMock
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), 0]

    exit_code, _, _, mock_processes, _, _ = _run_main_with_patches(
        ["with_server.py", "--server", "cmd", "--port", "9999", "--", "echo", "test"],
        is_server_ready_return_value=True,
        run_return_value=MagicMock(returncode=0),
        wait_side_effect=[subprocess.TimeoutExpired("cmd", 5), 0],
        popen_side_effect=[mock_process],
    )
    assert exit_code == 0
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()
    assert mock_process.wait.call_count == 2


def test_main_command_failure():
    """Test main returns command's exit code when command fails."""
    from unittest.mock import MagicMock
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = 0

    exit_code, _, _, _, _, _ = _run_main_with_patches(
        ["with_server.py", "--server", "cmd", "--port", "9999", "--", "false"],
        is_server_ready_return_value=True,
        run_return_value=MagicMock(returncode=1),
        popen_side_effect=[mock_process],
    )
    assert exit_code == 1


def test_main_strips_separator():
    """Test main handles the '--' separator correctly."""
    from unittest.mock import MagicMock
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = 0

    exit_code, _, _, _, mock_run, _ = _run_main_with_patches(
        ["with_server.py", "--server", "cmd", "--port", "9999", "--", "echo", "test"],
        is_server_ready_return_value=True,
        run_return_value=MagicMock(returncode=0),
        popen_side_effect=[mock_process],
    )
    assert exit_code == 0
    run_args = mock_run.call_args[0][0]
    assert run_args == ["echo", "test"]


def test_main_timeout_parameter():
    """Test main passes timeout to is_server_ready."""
    from unittest.mock import MagicMock, patch
    mock_process = MagicMock()
    mock_process.poll.return_value = None
    mock_process.wait.return_value = 0

    old_argv = sys.argv[:]
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    from io import StringIO
    sys.stdout = StringIO()
    sys.stderr = StringIO()

    original_is_server_ready = with_server.main.__globals__['is_server_ready']
    mock_is_server_ready = MagicMock(return_value=True)
    with_server.main.__globals__['is_server_ready'] = mock_is_server_ready

    try:
        sys.argv = ["with_server.py", "--server", "cmd", "--port", "9999", "--timeout", "10", "--", "echo", "test"]
        with patch('with_server.subprocess.Popen', return_value=mock_process):
            with patch('with_server.subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                try:
                    with_server.main()
                except SystemExit as e:
                    assert e.code == 0
        mock_is_server_ready.assert_called_with(9999, timeout=10)
    finally:
        with_server.main.__globals__['is_server_ready'] = original_is_server_ready
        sys.argv = old_argv
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def run_tests() -> int:
    tests = [
        ("is_server_ready_success", test_is_server_ready_success),
        ("is_server_ready_failure", test_is_server_ready_failure),
        ("is_server_ready_timeout", test_is_server_ready_timeout),
        ("main_mismatched_servers_ports", test_main_mismatched_servers_ports),
        ("main_no_command", test_main_no_command),
        ("main_single_server_success", test_main_single_server_success),
        ("main_multiple_servers_success", test_main_multiple_servers_success),
        ("main_server_fails_to_start", test_main_server_fails_to_start),
        ("main_server_terminate_timeout", test_main_server_terminate_timeout),
        ("main_command_failure", test_main_command_failure),
        ("main_strips_separator", test_main_strips_separator),
        ("main_timeout_parameter", test_main_timeout_parameter),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            import traceback
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run_tests())