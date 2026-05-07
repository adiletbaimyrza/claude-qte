"""Tests for :mod:`claude_qte.wrapper`."""

import socket
import threading
from unittest import mock

from claude_qte.wrapper import pick_free_port, run_command, wait_for_port


class TestPickFreePort:
    def test_returns_bindable_port(self):
        port = pick_free_port()
        assert 1024 <= port <= 65535
        # Port should still be free immediately after — bind to confirm.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))

    def test_distinct_ports_on_consecutive_calls(self):
        # Not strictly guaranteed, but the OS basically never hands the same
        # ephemeral port back-to-back.
        ports = {pick_free_port() for _ in range(5)}
        assert len(ports) > 1


class TestWaitForPort:
    def test_returns_false_for_unbound_port(self):
        port = pick_free_port()
        assert wait_for_port(port, timeout=0.3) is False

    def test_returns_true_when_listener_is_up(self):
        port = pick_free_port()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(1)

        # Accept-and-discard on a thread so the connect from wait_for_port
        # actually succeeds.
        def serve_one():
            try:
                conn, _ = sock.accept()
                conn.close()
            except OSError:
                pass

        t = threading.Thread(target=serve_one, daemon=True)
        t.start()
        try:
            assert wait_for_port(port, timeout=2.0) is True
        finally:
            sock.close()
            t.join(timeout=1.0)


class TestRunCommand:
    def test_run_command_with_empty_argv_exits_with_error(self, capsys):
        """Test that run_command exits with error when argv is empty."""
        # When argv is empty, the function should call sys.exit(2) which raises SystemExit
        import contextlib

        with (
            mock.patch("sys.stderr.write") as mock_stderr,
            mock.patch("sys.exit", side_effect=SystemExit(2)) as mock_exit,
        ):
            with contextlib.suppress(SystemExit):
                run_command([])
            mock_exit.assert_called_once_with(2)
            mock_stderr.assert_called_once_with("Usage: claude-qte run <command> [args...]\n")

    @mock.patch("claude_qte.wrapper.wait_for_port")
    @mock.patch("claude_qte.wrapper.subprocess.Popen")
    @mock.patch("claude_qte.wrapper.pick_free_port")
    @mock.patch("claude_qte.wrapper.current_invocation")
    @mock.patch("claude_qte.wrapper.os")
    @mock.patch("claude_qte.wrapper.signal")
    @mock.patch("claude_qte.wrapper.contextlib")
    def test_run_command_gate_start_failure(
        self,
        mock_contextlib,
        mock_signal,
        mock_os,
        mock_current_invocation,
        mock_pick_free_port,
        mock_popen,
        mock_wait_for_port,
        capsys,
    ):
        """Test run_command when gate fails to start."""
        # Setup mocks
        mock_pick_free_port.return_value = 9999
        mock_current_invocation.return_value = "/fake/binary"
        mock_wait_for_port.return_value = False  # Gate fails to start
        mock_proc = mock.Mock()
        mock_proc.poll.return_value = 1  # Process terminated
        mock_popen.return_value = mock_proc

        # Run the function
        with (
            mock.patch("sys.exit") as mock_exit,
            mock.patch("sys.stderr.write") as mock_stderr,
            mock.patch("claude_qte.wrapper.subprocess.run") as mock_subprocess_run,
        ):
            mock_subprocess_result = mock.Mock()
            mock_subprocess_result.returncode = 0
            mock_subprocess_run.return_value = mock_subprocess_result

            run_command(["echo", "hello"])

            assert mock_exit.call_count == 2
            mock_exit.assert_any_call(1)
            mock_exit.assert_any_call(0)

            mock_stderr.assert_called_once_with("claude-qte: gate did not start on port 9999\n")

            mock_contextlib.suppress.assert_any_call(OSError)
            mock_proc.terminate.assert_called_once()

    @mock.patch("claude_qte.wrapper.wait_for_port")
    @mock.patch("claude_qte.wrapper.subprocess.Popen")
    @mock.patch("claude_qte.wrapper.pick_free_port")
    @mock.patch("claude_qte.wrapper.current_invocation")
    @mock.patch("claude_qte.wrapper.os")
    @mock.patch("claude_qte.wrapper.signal")
    @mock.patch("claude_qte.wrapper.subprocess.run")
    def test_run_command_success(
        self,
        mock_subprocess_run,
        mock_signal,
        mock_os,
        mock_current_invocation,
        mock_pick_free_port,
        mock_popen,
        mock_wait_for_port,
    ):
        """Test successful run_command execution."""
        # Setup mocks
        mock_pick_free_port.return_value = 9999
        mock_current_invocation.return_value = "/fake/binary"
        mock_wait_for_port.return_value = True  # Gate starts successfully
        mock_proc = mock.Mock()
        mock_proc.poll.return_value = None  # Process still running
        mock_popen.return_value = mock_proc

        mock_subprocess_result = mock.Mock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_run.return_value = mock_subprocess_result

        # Run the function
        with mock.patch("sys.exit") as mock_exit:
            run_command(["echo", "hello"])

            mock_exit.assert_called_once_with(0)

            mock_subprocess_run.assert_called_once()
            args, _ = mock_subprocess_run.call_args
            assert args[0] == ["echo", "hello"]
            assert mock_signal.signal.call_count >= 2

    @mock.patch("claude_qte.wrapper.wait_for_port")
    @mock.patch("claude_qte.wrapper.subprocess.Popen")
    @mock.patch("claude_qte.wrapper.pick_free_port")
    @mock.patch("claude_qte.wrapper.current_invocation")
    @mock.patch("claude_qte.wrapper.os")
    @mock.patch("claude_qte.wrapper.signal")
    def test_run_command_signal_handling(
        self,
        mock_signal,
        mock_os,
        mock_current_invocation,
        mock_pick_free_port,
        mock_popen,
        mock_wait_for_port,
    ):
        """Test that signal handlers are properly set up."""
        # Setup mocks
        mock_pick_free_port.return_value = 9999
        mock_current_invocation.return_value = "/fake/binary"
        mock_wait_for_port.return_value = True
        mock_proc = mock.Mock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        # Run the function (we'll mock subprocess.run to avoid actually running a command)
        with mock.patch("claude_qte.wrapper.subprocess.run") as mock_subprocess_run:
            mock_subprocess_result = mock.Mock()
            mock_subprocess_result.returncode = 0
            mock_subprocess_run.return_value = mock_subprocess_result

            with mock.patch("sys.exit"):
                run_command(["echo", "hello"])

                # Verify signal handlers were set up by checking that signal.signal was called
                # with the expected signal numbers and handler functions
                assert mock_signal.signal.call_count >= 3

                signal_numbers = [call[0][0] for call in mock_signal.signal.call_args_list]
                assert mock_signal.SIGTERM in signal_numbers
                assert mock_signal.SIGHUP in signal_numbers
                assert mock_signal.SIGINT in signal_numbers
