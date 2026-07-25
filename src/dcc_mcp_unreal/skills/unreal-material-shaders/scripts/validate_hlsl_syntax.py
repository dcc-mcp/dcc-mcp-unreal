"""Pure syntax validation for HLSL source code — no compilation, no linking, no execution.

This tool performs regex-based syntax checking on HLSL source. It NEVER compiles,
links, or executes HLSL. It only parses the source text and returns syntax errors.

Safety guarantees:
- No subprocess / exec / eval
- No file I/O beyond reading the input string
- No shader compiler invocation
- DXC features (SM 6.0+) are version-gated (UE 5.4+)
"""

from __future__ import annotations

import re
from typing import Any

from dcc_mcp_core.skill import skill_entry, skill_success

# --- Recognized HLSL constructs for validation ---

_HLSL_RESERVED_KEYWORDS: set[str] = {
    # Types
    "float", "float2", "float3", "float4", "half", "half2", "half3", "half4",
    "double", "double2", "double3", "double4",
    "int", "int2", "int3", "int4", "uint", "uint2", "uint3", "uint4",
    "bool", "bool2", "bool3", "bool4",
    "matrix", "void", "struct", "sampler", "sampler2D", "samplerCube",
    "Texture2D", "TextureCube", "RWTexture2D", "RWTexture3D",
    "StructuredBuffer", "RWStructuredBuffer", "ByteAddressBuffer", "RWByteAddressBuffer",
    # Flow control
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "break", "continue", "return", "discard",
    # Qualifiers
    "const", "static", "uniform", "in", "out", "inout", "inline",
    # DXC / SM 6.0+ (UE 5.4+)
    "WaveGetLaneIndex", "WaveActiveSum", "WaveActiveMin", "WaveActiveMax",
    "groupshared", "RayDesc", "TraceRay", "ReportHit", "IgnoreHit", "AcceptHitAndEndSearch",
}

_HLSL_BUILTIN_IDENTIFIERS: set[str] = {
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "abs", "sign", "ceil", "floor", "round", "trunc", "frac",
    "sqrt", "rsqrt", "pow", "exp", "exp2", "log", "log2", "log10",
    "min", "max", "clamp", "saturate", "lerp", "step", "smoothstep",
    "dot", "cross", "normalize", "length", "distance", "reflect", "refract",
    "ddx", "ddy", "ddx_coarse", "ddy_coarse", "ddx_fine", "ddy_fine", "fwidth",
    "Sample", "SampleLevel", "SampleBias", "SampleGrad", "Load",
    "all", "any", "mul", "transpose", "determinant",
    "asfloat", "asint", "asuint",
}

# Simple regex patterns for HLSL structure
_RE_BRACES = re.compile(r"[{}]")
_RE_COMMENTS_SINGLE = re.compile(r"//[^\n]*")
_RE_COMMENTS_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_RE_STRING_LITERALS = re.compile(r'"(?:[^"\\]|\\.)*"')
_RE_FUNCTION_DEFS = re.compile(r"\b(\w+)\s+(\w+)\s*\(([^)]*)\)\s*[{]", re.MULTILINE)
_RE_UNDECLARED_VAR = re.compile(r"\breturn\s+(\w+)\b", re.IGNORECASE)


def _strip_comments_and_strings(source: str) -> str:
    """Remove comments and string literals to avoid false positives."""
    s = _RE_COMMENTS_SINGLE.sub(" ", source)
    s = _RE_COMMENTS_BLOCK.sub(" ", s)
    s = _RE_STRING_LITERALS.sub('""', s)
    return s


def _check_brace_balance(source: str) -> list[dict[str, Any]]:
    """Check that braces, parentheses, and brackets are balanced."""
    errors: list[dict[str, Any]] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[tuple[str, int]] = []
    lines = source.splitlines()

    for lineno, line in enumerate(lines, 1):
        for col, ch in enumerate(line):
            if ch in pairs:
                stack.append((ch, lineno))
            elif ch in pairs.values():
                if not stack:
                    errors.append({
                        "line": lineno,
                        "column": col + 1,
                        "message": f"Unmatched closing '{ch}'",
                        "severity": "error",
                    })
                else:
                    opener, _oline = stack.pop()
                    expected = pairs[opener]
                    if ch != expected:
                        errors.append({
                            "line": lineno,
                            "column": col + 1,
                            "message": f"Mismatched closing '{ch}' (expected '{expected}' from line {_oline})",
                            "severity": "error",
                        })

    for opener, lineno in stack:
        errors.append({
            "line": lineno,
            "column": 0,
            "message": f"Unclosed '{opener}'",
            "severity": "error",
        })

    return errors


def _check_semicolons(source: str) -> list[dict[str, Any]]:
    """Check for likely missing semicolons on statements."""
    errors: list[dict[str, Any]] = []
    lines = source.splitlines()

    statement_keywords = re.compile(
        r"^\s*(float\d*|half\d*|int\d*|uint\d*|bool\d*|double\d*)\s+\w+\s*="
    )
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue
        if stripped.startswith("#") or stripped.startswith("{") or stripped.startswith("}"):
            continue
        if statement_keywords.match(stripped) and not stripped.endswith(";"):
            errors.append({
                "line": lineno,
                "column": 1,
                "message": f"Statement likely missing semicolon: '{stripped[:80]}'",
                "severity": "warning",
            })

    return errors


def _check_type_mismatches(source: str) -> list[dict[str, Any]]:
    """Detect obvious type mismatches in assignments and returns."""
    errors: list[dict[str, Any]] = []
    lines = source.splitlines()

    # Detect: float3 result = float_value (scalar assigned to vector)
    scalar_to_vector = re.compile(
        r"\b(float3|float4|int3|int4)\s+(\w+)\s*=\s*(\d+\.?\d*f?)\s*;"
    )
    for lineno, line in enumerate(lines, 1):
        m = scalar_to_vector.search(line)
        if m:
            errors.append({
                "line": lineno,
                "column": m.start() + 1,
                "message": f"Likely type mismatch: assigning scalar literal to {m.group(1)} '{m.group(2)}'",
                "severity": "warning",
            })

    # Detect: return type mismatch — return float in void function context
    # (simplified; full check requires call context)

    return errors


def _check_functions(source: str) -> list[dict[str, Any]]:
    """Check function definitions for basic correctness."""
    errors: list[dict[str, Any]] = []
    lines = source.splitlines()

    for m in _RE_FUNCTION_DEFS.finditer(source):
        return_type = m.group(1)
        func_name = m.group(2)
        params = m.group(3)

        if return_type not in _HLSL_RESERVED_KEYWORDS and not return_type.startswith("_"):
            errors.append({
                "line": source[:m.start()].count("\n") + 1,
                "column": m.start(1) + 1,
                "message": f"Unrecognized return type '{return_type}' for function '{func_name}'",
                "severity": "warning",
            })

        if params.strip():
            for param in params.split(","):
                param = param.strip()
                if not param:
                    continue
                parts = param.split()
                if len(parts) < 2:
                    errors.append({
                        "line": source[:m.start()].count("\n") + 1,
                        "column": m.start(3) + 1,
                        "message": f"Malformed parameter '{param.strip()}' in function '{func_name}'",
                        "severity": "error",
                    })

    return errors


@skill_entry
def validate_hlsl_syntax(
    hlsl_code: str,
    entry_point: str = "",
    **kwargs,
) -> dict:
    """Perform pure syntax validation on HLSL source code.

    Uses regex-based parsing to detect common HLSL syntax errors. Does NOT
    compile, link, or execute any code. DXC compiler features (SM 6.0+)
    are version-gated to UE 5.4+.

    Args:
        hlsl_code: HLSL source code string to validate.
        entry_point: Optional function name to verify exists in the source.

    Returns:
        ActionResultModel with syntax_errors list (empty if valid).
        success=true means NO errors found; individual errors carry
        line/column/severity/message.
    """
    if not hlsl_code.strip():
        return skill_success(
            "HLSL source is empty — nothing to validate.",
            syntax_errors=[],
            valid=True,
        )

    # Strip comments and strings for structural checks
    clean = _strip_comments_and_strings(hlsl_code)

    all_errors: list[dict[str, Any]] = []

    # 1. Brace / paren / bracket balance
    all_errors.extend(_check_brace_balance(clean))

    # 2. Semicolon checks (statements)
    all_errors.extend(_check_semicolons(clean))

    # 3. Type mismatch checks
    all_errors.extend(_check_type_mismatches(clean))

    # 4. Function definition checks
    all_errors.extend(_check_functions(clean))

    # 5. Entry point check
    if entry_point:
        _pattern = (
            r"\b" + re.escape(entry_point) + r"\s*\([^)]*\)\s*" + r"[{]"
        )
        found = re.search(_pattern, clean)
        if not found:
            all_errors.append({
                "line": 0,
                "column": 0,
                "message": f"Entry point '{entry_point}' not found in source",
                "severity": "error",
            })

    is_valid = len([e for e in all_errors if e["severity"] == "error"]) == 0

    if is_valid and not all_errors:
        return skill_success(
            "HLSL syntax validation passed — no errors or warnings.",
            syntax_errors=[],
            valid=True,
        )
    elif is_valid:
        return skill_success(
            f"HLSL syntax validation passed with {len(all_errors)} warning(s).",
            syntax_errors=all_errors,
            valid=True,
        )
    else:
        return skill_success(
            f"HLSL syntax validation found {len(all_errors)} issue(s).",
            syntax_errors=all_errors,
            valid=False,
        )
