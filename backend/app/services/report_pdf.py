"""PDF report (ReportLab). Completed exams -> final report; others -> 'QORALAMA' watermark (doctor/admin only)."""

from __future__ import annotations

import os
from io import BytesIO
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONT_CACHE: tuple[str, str] | None = None
_SUBST = str.maketrans(
    {"\u02bb": "'", "\u02bc": "'", "\u2019": "'", "\u2018": "'", "\u2013": "-", "\u2014": "-", "\u00a0": " "}
)


def _fonts() -> tuple[str, str]:
    """(regular, bold) font names. Prefers DejaVu (wider coverage), falls back to Vera bundled with reportlab."""
    global _FONT_CACHE
    if _FONT_CACHE:
        return _FONT_CACHE
    cands = [
        (os.environ.get("PDF_FONT_PATH", ""), os.environ.get("PDF_FONT_BOLD_PATH", "")),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for reg, bold in cands:
        if reg and Path(reg).exists() and bold and Path(bold).exists():
            pdfmetrics.registerFont(TTFont("CP-Regular", reg))
            pdfmetrics.registerFont(TTFont("CP-Bold", bold))
            _FONT_CACHE = ("CP-Regular", "CP-Bold")
            return _FONT_CACHE
    import reportlab

    d = Path(reportlab.__file__).parent / "fonts"
    pdfmetrics.registerFont(TTFont("CP-Regular", str(d / "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("CP-Bold", str(d / "VeraBd.ttf")))
    _FONT_CACHE = ("CP-Regular", "CP-Bold")
    return _FONT_CACHE


def S(v: Any) -> str:
    """Escape for Paragraph + normalise Uzbek modifier letters to ASCII apostrophe."""
    return escape("" if v is None else str(v)).translate(_SUBST)


def _waveform_drawing(peaks: dict[str, Any] | None, width: float, height: float = 28 * mm) -> Drawing:
    d = Drawing(width, height)
    d.add(Rect(0, 0, width, height, strokeColor=colors.lightgrey, fillColor=colors.whitesmoke))
    d.add(Line(0, height / 2, width, height / 2, strokeColor=colors.lightgrey))
    if peaks and peaks.get("data"):
        data = peaks["data"]
        n = len(data) // 2
        step = width / max(n, 1)
        mid = height / 2
        for i in range(n):
            mn, mx = data[2 * i], data[2 * i + 1]
            x = i * step
            d.add(
                Line(
                    x,
                    mid + mn * mid * 0.95,
                    x,
                    mid + mx * mid * 0.95,
                    strokeColor=colors.HexColor("#0f766e"),
                    strokeWidth=max(step, 0.4),
                )
            )
    else:
        d.add(
            String(
                width / 2,
                height / 2 - 3,
                "waveform mavjud emas",
                textAnchor="middle",
                fontName=_fonts()[0],
                fontSize=8,
            )
        )
    return d


def build_pdf(
    *,
    clinic: dict[str, str],
    exam: dict[str, Any],
    patient: dict[str, Any],
    analysis: dict[str, Any] | None,
    recordings: list[dict[str, Any]],
    report: dict[str, Any] | None,
    drugs: list[dict[str, Any]],
    conclusion: dict[str, Any] | None,
    doctor: dict[str, Any] | None,
    verify_url: str | None,
    draft: bool,
) -> bytes:
    reg, bold = _fonts()
    base = getSampleStyleSheet()
    st = {
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=16,
            textColor=colors.HexColor("#0f766e"),
            spaceAfter=4,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=11.5,
            spaceBefore=9,
            spaceAfter=3,
            textColor=colors.HexColor("#134e4a"),
        ),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontName=reg, fontSize=9, leading=12),
        "small": ParagraphStyle(
            "small", parent=base["BodyText"], fontName=reg, fontSize=7.5, leading=10, textColor=colors.grey
        ),
        "warn": ParagraphStyle(
            "warn",
            parent=base["BodyText"],
            fontName=reg,
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#92400e"),
            backColor=colors.HexColor("#fffbeb"),
            borderPadding=4,
        ),
    }
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title=f"CardioPCG {exam['exam_no']}",
        author="CardioPCG AI",
    )
    width = A4[0] - 32 * mm
    el: list[Any] = []

    def table(rows: list[list[Any]], col_widths: list[float] | None = None, header: bool = False) -> Table:
        t = Table(
            [[Paragraph(S(c), st["p"]) if not hasattr(c, "wrap") else c for c in r] for r in rows],
            colWidths=col_widths,
        )
        style = [
            ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        if header:
            style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ecfdf5")))
        t.setStyle(TableStyle(style))
        return t

    el.append(Paragraph(S(clinic.get("name") or "CardioPCG AI"), st["h1"]))
    el.append(
        Paragraph(
            S(
                f"Fonokardiografiya (PCG) tahlili hisoboti - {exam['exam_no']}"
                + ("  [QORALAMA]" if draft else "")
            ),
            st["p"],
        )
    )
    el.append(Spacer(1, 4))
    el.append(
        Paragraph(
            S(
                "Tizim qaror qo'llab-quvvatlash vositasi bo'lib, sertifikatsiyalangan tibbiy qurilma emas. Yakuniy tashxisni shifokor qo'yadi."
            ),
            st["warn"],
        )
    )

    el.append(Paragraph("Bemor", st["h2"]))
    el.append(
        table(
            [
                ["F.I.Sh.", patient["full_name"], "MRN", patient["mrn"]],
                [
                    "Yosh / jins",
                    f"{patient['age']} / {patient['gender']}",
                    "Tug'ilgan sana",
                    patient["birth_date"],
                ],
            ],
            [25 * mm, 70 * mm, 28 * mm, width - 123 * mm],
        )
    )

    el.append(Paragraph("Tekshiruv", st["h2"]))
    vit = ", ".join(f"{k}: {v}" for k, v in exam["vitals"].items() if v is not None) or "-"
    el.append(
        table(
            [
                ["Sana", exam["examined_at"], "Muhimlik", exam["priority"]],
                ["Shikoyat", exam.get("complaints") or "-", "Vitallar", vit],
            ],
            [25 * mm, 70 * mm, 28 * mm, width - 123 * mm],
        )
    )

    if analysis:
        el.append(Paragraph("Signal tahlili", st["h2"]))
        probs = ", ".join(f"{k}: {v:.2f}" for k, v in (analysis.get("class_probs") or {}).items())
        el.append(
            table(
                [
                    [
                        "Sinf",
                        f"{analysis['pcg_class']} (ishonch {analysis['confidence']:.2f})",
                        "Og'irlik",
                        analysis["severity"],
                    ],
                    ["Ehtimollar", probs, "Model", analysis["model_version"]],
                    [
                        "YUCh (bpm)",
                        analysis.get("heart_rate_bpm") or "-",
                        "S1/S2 soni",
                        f"{analysis.get('s1_count') or '-'} / {analysis.get('s2_count') or '-'}",
                    ],
                    [
                        "Sistola / diastola (ms)",
                        f"{analysis.get('systole_ms') or '-'} / {analysis.get('diastole_ms') or '-'}",
                        "Shovqin",
                        f"{analysis.get('murmur_timing')} {analysis.get('murmur_grade') or ''}".strip(),
                    ],
                ],
                [34 * mm, 62 * mm, 25 * mm, width - 121 * mm],
            )
        )

    for rec in recordings:
        block: list[Any] = [
            Paragraph(
                S(
                    f"Yozuv: {rec['site']} ({rec.get('duration_sec') or '?'} s, SNR {rec.get('snr_db') or '-'} dB)"
                ),
                st["h2"],
            )
        ]
        block.append(_waveform_drawing(rec.get("peaks"), width))
        if rec.get("spectrogram_png"):
            try:
                from PIL import Image as _PILImage

                _PILImage.open(BytesIO(rec["spectrogram_png"])).load()  # validate before handing to reportlab
                img = ImageReader(BytesIO(rec["spectrogram_png"]))
                iw, ih = img.getSize()
                block.append(Spacer(1, 3))
                block.append(
                    Image(BytesIO(rec["spectrogram_png"]), width=width, height=min(width * ih / iw, 60 * mm))
                )
            except Exception:  # noqa: S110 - a broken image must not break the whole report
                pass
        el.append(KeepTogether(block))

    if report:
        el.append(Paragraph("AI izohi (qaror qo'llab-quvvatlash)", st["h2"]))
        el.append(Paragraph(S(report.get("summary") or "-"), st["p"]))
        dd = report.get("differential_diagnoses") or []
        if dd:
            el.append(Spacer(1, 3))
            el.append(
                table(
                    [["Differensial tashxis", "ICD-10", "Ehtimol", "Asos"]]
                    + [[d.get("name"), d.get("icd10"), d.get("likelihood"), d.get("rationale")] for d in dd],
                    [48 * mm, 18 * mm, 20 * mm, width - 86 * mm],
                    header=True,
                )
            )
        if report.get("recommended_tests"):
            el.append(
                Paragraph(
                    S("Tavsiya etilgan tekshiruvlar: " + ", ".join(report["recommended_tests"])), st["p"]
                )
            )
        el.append(Paragraph(S(report.get("disclaimer") or ""), st["small"]))

    if drugs:
        el.append(Paragraph("Tasdiqlangan dori vositalari", st["h2"]))
        el.append(
            table(
                [["Dori", "Doza", "Qabul", "Davomiylik", "Izoh"]]
                + [
                    [
                        d["drug_name"],
                        d["dose"],
                        f"{d['route']}, {d['frequency']}",
                        f"{d.get('duration_days') or '-'} kun",
                        d.get("instructions") or d.get("rationale") or "",
                    ]
                    for d in drugs
                ],
                [40 * mm, 20 * mm, 45 * mm, 22 * mm, width - 127 * mm],
                header=True,
            )
        )

    if conclusion:
        el.append(Paragraph("Shifokor xulosasi", st["h2"]))
        el.append(
            table(
                [
                    ["Tashxis", conclusion["diagnosis_text"]],
                    ["ICD-10", ", ".join(conclusion.get("icd10_codes") or []) or "-"],
                    [
                        "Yakuniy baho",
                        f"{conclusion['final_pcg_class']} / {conclusion['final_severity']} (AI bilan: {conclusion['agreement_with_ai']})",
                    ],
                    ["Tavsiyalar", conclusion["recommendations"]],
                    [
                        "Nazorat",
                        f"{conclusion.get('follow_up_date') or '-'} {conclusion.get('follow_up_notes') or ''}".strip(),
                    ],
                ],
                [30 * mm, width - 30 * mm],
            )
        )
        sig_rows = [
            [
                Paragraph(
                    "<br/>".join(
                        S(x)
                        for x in (
                            doctor["full_name"] if doctor else "-",
                            f"Litsenziya: {(doctor or {}).get('license_no') or '-'}",
                            f"Imzolangan: {conclusion.get('signed_at') or '-'}",
                            f"SHA-256: {(conclusion.get('signature_hash') or '-')[:32]}...",
                        )
                    ),
                    st["p"],
                ),
            ]
        ]
        if verify_url and conclusion.get("signature_hash"):
            code = qr.QrCodeWidget(verify_url)
            b = code.getBounds()
            w, h = b[2] - b[0], b[3] - b[1]
            qd = Drawing(26 * mm, 26 * mm, transform=[26 * mm / w, 0, 0, 26 * mm / h, 0, 0])
            qd.add(code)
            sig_rows[0].append(qd)
        sig = Table(sig_rows, colWidths=[width - 30 * mm, 28 * mm] if len(sig_rows[0]) == 2 else [width])
        sig.setStyle(
            TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")])
        )
        el.append(Spacer(1, 6))
        el.append(KeepTogether([sig]))

    footer_text = clinic.get("footer") or ""

    def decorate(canvas, doc_):
        canvas.saveState()
        if draft:
            canvas.setFont(bold, 70)
            canvas.setFillColor(colors.Color(0.85, 0.1, 0.1, alpha=0.12))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "QORALAMA")
            canvas.rotate(-45)
            canvas.translate(-A4[0] / 2, -A4[1] / 2)
        canvas.setFont(reg, 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(
            16 * mm, 10 * mm, S("Hujjat tizimda yaratilgan (CardioPCG AI). " + footer_text)[:150]
        )
        canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"{doc_.page}")
        canvas.restoreState()

    doc.build(el, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
