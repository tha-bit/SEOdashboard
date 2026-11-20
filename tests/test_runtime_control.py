from __future__ import annotations

import socket
import threading
import time

from backend.launcher import _available_port
from backend.runtime_control import (
    automatic_shutdown_enabled,
    clear_shutdown_configuration,
    configure_shutdown,
    register_browser_session,
    request_shutdown,
    runtime_status,
    unregister_browser_session,
)
from backend.services.cache import (
    clear_all_caches,
    get_cached_architecture_issues,
    get_cached_snapshot_counts,
    invalidate_project_cache,
    set_cached_architecture_issues,
    set_cached_snapshot_counts,
)


def test_automatic_shutdown_waits_for_last_browser_and_grace_period():
    stopped = threading.Event()
    configure_shutdown(stopped.set, "private-token", automatic=True, grace_seconds=0.12)
    try:
        first = register_browser_session()
        second = register_browser_session()
        assert first and second
        assert runtime_status()["active_browser_sessions"] == 2

        unregister_browser_session(first)
        assert not stopped.wait(0.2)
        assert runtime_status()["active_browser_sessions"] == 1

        unregister_browser_session(second)
        assert stopped.wait(0.5)
        assert not automatic_shutdown_enabled()
    finally:
        clear_shutdown_configuration()


def test_reconnection_cancels_pending_automatic_shutdown():
    stopped = threading.Event()
    configure_shutdown(stopped.set, "private-token", automatic=True, grace_seconds=0.15)
    try:
        first = register_browser_session()
        assert first
        unregister_browser_session(first)
        time.sleep(0.04)

        replacement = register_browser_session()
        assert replacement
        assert not stopped.wait(0.25)

        unregister_browser_session(replacement)
        assert stopped.wait(0.5)
    finally:
        clear_shutdown_configuration()


def test_manual_shutdown_remains_available_when_automatic_mode_is_disabled():
    stopped = threading.Event()
    configure_shutdown(stopped.set, "private-token", automatic=False)
    try:
        assert register_browser_session() is None
        assert request_shutdown("incorrect-token") is False
        assert not stopped.is_set()
        assert request_shutdown("private-token") is True
        assert stopped.wait(0.2)
    finally:
        clear_shutdown_configuration()


def test_multiple_tabs_and_windows_lifecycle():
    stopped = threading.Event()
    configure_shutdown(stopped.set, "multi-tab-token", automatic=True, grace_seconds=0.15)
    try:
        tab1 = register_browser_session()
        tab2 = register_browser_session()
        tab3 = register_browser_session()
        assert tab1 and tab2 and tab3
        assert runtime_status()["active_browser_sessions"] == 3

        # Close Tab 1 - 2 remain
        unregister_browser_session(tab1)
        time.sleep(0.05)
        assert runtime_status()["active_browser_sessions"] == 2
        assert not stopped.is_set()

        # Close Tab 2 - 1 remains
        unregister_browser_session(tab2)
        time.sleep(0.05)
        assert runtime_status()["active_browser_sessions"] == 1
        assert not stopped.is_set()

        # Close Tab 3 (final tab) - should trigger shutdown after grace period
        unregister_browser_session(tab3)
        assert stopped.wait(0.5)
        assert runtime_status()["active_browser_sessions"] == 0
    finally:
        clear_shutdown_configuration()


def test_repeated_launch_and_shutdown_cycles():
    for cycle in range(5):
        stopped = threading.Event()
        configure_shutdown(stopped.set, f"cycle-token-{cycle}", automatic=True, grace_seconds=0.08)
        try:
            session = register_browser_session()
            assert session
            assert runtime_status()["active_browser_sessions"] == 1
            unregister_browser_session(session)
            assert stopped.wait(0.4)
            assert runtime_status()["active_browser_sessions"] == 0
        finally:
            clear_shutdown_configuration()


def test_cache_invalidation_prunes_snapshot_and_project_structures():
    clear_all_caches()
    set_cached_architecture_issues("proj-1", [{"type": "issue_1"}])
    set_cached_snapshot_counts("snap-1", {"p1": {"inlinks": 5, "unique_sources": 2}})
    assert get_cached_architecture_issues("proj-1") is not None
    assert get_cached_snapshot_counts("snap-1") is not None

    invalidate_project_cache("proj-1")
    assert get_cached_architecture_issues("proj-1") is None
    assert get_cached_snapshot_counts("snap-1") is None


def test_available_port_handles_port_collision():
    # Bind an ephemeral port then ask _available_port to find one starting from that port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        taken_port = candidate.getsockname()[1]
        import os
        original = os.environ.get("SEO_RUNTIME_PORT")
        try:
            os.environ["SEO_RUNTIME_PORT"] = str(taken_port)
            # When SEO_RUNTIME_PORT is explicitly set and taken, it should raise RuntimeError
            import pytest
            with pytest.raises(RuntimeError):
                _available_port()
        finally:
            if original is not None:
                os.environ["SEO_RUNTIME_PORT"] = original
            else:
                os.environ.pop("SEO_RUNTIME_PORT", None)
