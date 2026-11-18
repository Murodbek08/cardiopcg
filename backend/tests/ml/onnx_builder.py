"""Hand-encodes a tiny ONNX model (Gemm + Sigmoid) without the `onnx` package, for registry tests.

p = sigmoid(X @ W + B) with X: [1, n_features]. Pure protobuf wire-format encoding.
"""

from __future__ import annotations

import struct


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _key(field: int, wt: int) -> bytes:
    return _varint((field << 3) | wt)


def _ld(field: int, payload: bytes) -> bytes:
    return _key(field, 2) + _varint(len(payload)) + payload


def _s(field: int, s: str) -> bytes:
    return _ld(field, s.encode())


def _i(field: int, v: int) -> bytes:
    return _key(field, 0) + _varint(v)


def _tensor(name: str, dims: list[int], floats: list[float]) -> bytes:
    b = b"".join(_i(1, d) for d in dims) + _i(2, 1)
    b += _ld(4, b"".join(struct.pack("<f", f) for f in floats))  # packed float_data
    b += _s(8, name)
    return b


def _value_info(name: str, dims: list[int]) -> bytes:
    shape = b"".join(_ld(1, _i(1, d)) for d in dims)
    tensor_type = _i(1, 1) + _ld(2, shape)
    return _s(1, name) + _ld(2, _ld(1, tensor_type))


def build_logistic_onnx(weights: list[float], bias: float) -> bytes:
    n = len(weights)
    gemm = _s(1, "X") + _s(1, "W") + _s(1, "B") + _s(2, "Z") + _s(3, "gemm") + _s(4, "Gemm")
    sig = _s(1, "Z") + _s(2, "Y") + _s(3, "sig") + _s(4, "Sigmoid")
    graph = _ld(1, gemm) + _ld(1, sig) + _s(2, "g")
    graph += _ld(5, _tensor("W", [n, 1], weights)) + _ld(5, _tensor("B", [1], [bias]))
    graph += _ld(11, _value_info("X", [1, n])) + _ld(12, _value_info("Y", [1, 1]))
    opset = _s(1, "") + _i(2, 13)
    return _i(1, 8) + _ld(7, graph) + _ld(8, opset)
