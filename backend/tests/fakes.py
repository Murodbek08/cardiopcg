"""Fake AnalysisService - ONLY for tests (the real engine is app.services.ai_adapter)."""

from __future__ import annotations

from app.services.analysis_port import (
    AiReportData,
    AnalysisError,
    AnalysisOutcome,
    AnalysisRequest,
    DrugSuggestion,
    RecordingArtifacts,
    ReportOutcome,
    ReportRequest,
    SegmentOut,
    SignalAnalysis,
    TransientAnalysisError,
)


def _png() -> bytes:
    import io

    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (8, 4), "navy").save(b, "PNG")
    return b.getvalue()


PNG_1x1 = _png()


class FakeAnalysis:
    def __init__(self) -> None:
        self.pcg_class = "murmur"
        self.severity = "moderate"
        self.confidence = 0.88
        self.red_flags: list[str] = []
        self.llm_fail = False
        self.fail_code: str | None = None
        self.transient_failures = 0
        self.drugs = [
            DrugSuggestion(
                drug_name="Furosemid",
                inn_code="furosemide",
                atc_code="C03CA01",
                dose="20 mg",
                frequency="kuniga 1 marta",
                duration_days=14,
                rationale="hajm yuklamasi",
            ),
        ]
        self.requests: list[AnalysisRequest] = []
        self.report_requests: list[ReportRequest] = []

    def _report(self) -> ReportOutcome:
        if self.llm_fail:
            return ReportOutcome(report=None, error="LLM timeout")
        return ReportOutcome(
            report=AiReportData(
                llm_model="fake-llm",
                prompt_version="v-test",
                summary="Mitral nuqtada sistolik shovqin.",
                findings={"murmur": {"present": True}},
                differential_diagnoses=[{"name": "MR", "likelihood": "high"}],
                recommended_tests=["Exo-KG"],
                red_flags=self.red_flags,
                patient_friendly_text="matn",
                disclaimer="AI faqat qo'llab-quvvatlash",
                prompt_tokens=100,
                completion_tokens=50,
                latency_ms=900,
                cost_usd=0.0012,
            ),
            drug_suggestions=list(self.drugs),
        )

    async def analyze(self, request: AnalysisRequest, progress=None) -> AnalysisOutcome:
        self.requests.append(request)
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise TransientAnalysisError("NET", "temporary")
        if self.fail_code:
            raise AnalysisError(self.fail_code, "deterministic failure")
        for stage, pct in (("preprocessing", 25), ("segmenting", 40), ("classifying", 70)):
            if progress:
                await progress(stage, pct)
        r0 = request.recordings[0]
        sig = SignalAnalysis(
            model_version=request.options.model_version,
            pcg_class=self.pcg_class,
            class_probs={"normal": 0.1, "murmur": 0.85, "extra_heart_sound": 0.03, "artifact": 0.02},
            confidence=self.confidence,
            severity=self.severity,
            murmur_timing="systolic",
            murmur_grade=3,
            heart_rate_bpm=72.0,
            s1_count=10,
            s2_count=10,
            systole_ms=300.0,
            diastole_ms=500.0,
            segments=[
                SegmentOut(recording_id=r0.recording_id, type="S1", start_ms=100, end_ms=160, cycle_no=1),
                SegmentOut(recording_id=r0.recording_id, type="S2", start_ms=400, end_ms=450, cycle_no=1),
                SegmentOut(
                    recording_id=r0.recording_id, type="S2", start_ms=500, end_ms=400
                ),  # invalid: skipped
            ],
            recordings=[
                RecordingArtifacts(
                    recording_id=r.recording_id,
                    pcg_class=self.pcg_class,
                    confidence=self.confidence,
                    spectrogram_png=PNG_1x1,
                    waveform_peaks={
                        "sample_rate": 4000,
                        "samples_per_pixel": 10,
                        "data": [-0.5, 0.5, -0.2, 0.3],
                    },
                )
                for r in request.recordings
            ],
        )
        return AnalysisOutcome(signal=sig, report=self._report() if request.options.llm else None)

    async def generate_report(self, request: ReportRequest) -> ReportOutcome:
        self.report_requests.append(request)
        out = self._report()
        if not request.want_drugs:
            out.drug_suggestions = []
        return out
