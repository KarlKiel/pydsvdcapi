"""Tests for pydsvdcapi.addons.converter public API."""

import pytest

from pydsvdcapi.addons.converter import apply_converter, compile_converter


def test_compile_converter_simple_expression():
    fn = compile_converter("value = value * 2")
    assert fn(5) == 10


def test_compile_converter_multiline():
    fn = compile_converter("""
        if value > 100:
            value = 100
    """)
    assert fn(200) == 100
    assert fn(50) == 50


def test_compile_converter_syntax_error_raises():
    with pytest.raises(SyntaxError):
        compile_converter("value = ??? bad syntax")


def test_apply_converter_none_is_passthrough():
    assert apply_converter(None, 42, component_id="x", direction="uplink") == 42


def test_apply_converter_calls_fn():
    fn = compile_converter("value = value + 1")
    assert apply_converter(fn, 10, component_id="x", direction="uplink") == 11


def test_apply_converter_on_exception_returns_original(caplog):
    fn = compile_converter("raise ValueError('boom')")
    result = apply_converter(fn, 99, component_id="my_sensor", direction="downlink")
    assert result == 99
    assert "Converter error" in caplog.text
