"""Port (Protocol) between the backend core and the AI/analysis engine (doc 02 / doc 01).

Kept deliberately simple: input = audio/image bytes or a path + a de-identified context dict,
output = Pydantic result. The backend agent may define its own `app/services/analysis_port.py`;
any object satisfying this Protocol (structurally) can be plugged in.

Errors:
  * invalid/too-short/low-sample-rate input -> `app.ml.AudioError` (has `.code`, e.g. SAMPLE_RATE_TOO_LOW,
    AUDIO_TOO_SHORT, AUDIO_DECODE_FAILED, IMAGE_TOO_SMALL, CALIBRATION_REQUIRED)
  * AI problems NEVER raise out of `analyze`: they are reported in `AnalysisOutput.ai.status`
    (unavailable | rate_limited | budget_exceeded | consent_missing | blocked_low_quality | skipped).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from app.ml.schemas import PcgAnalysisResult

from .schemas import AnalysisOptions, AnalysisOutput


@runtime_checkable
class AnalysisPort(Protocol):
    async def analyze(
        self,
        audio: bytes | str | os.PathLike[str],
        context: Mapping[str, Any] | None = None,
        options: AnalysisOptions | Mapping[str, Any] | None = None,
    ) -> AnalysisOutput:
        """Signal pipeline [2]-[8] + (optionally) AI clinical assessment and drug proposals [9]-[10]."""
        ...

    async def regenerate_ai(
        self,
        pcg: PcgAnalysisResult,
        context: Mapping[str, Any] | None = None,
        options: AnalysisOptions | Mapping[str, Any] | None = None,
    ) -> AnalysisOutput:
        """Re-run only the AI stages on an existing PCG result (`POST /exams/{id}/ai/assess`)."""
        ...
